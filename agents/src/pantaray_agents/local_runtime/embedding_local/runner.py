"""CPU inference for the bundled embedding model: onnxruntime + tokenizers.

The model file, the tokenizer and every preprocessing decision come from the
manifest. This module only knows how to tokenize, run the graph, pool and
normalize.
"""

from __future__ import annotations

import threading
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

import numpy
from numpy.typing import NDArray

from .manifest import (
    LocalEmbeddingManifest,
    LocalEmbeddingPooling,
    LocalEmbeddingUnavailableError,
    require_chunk_fits_window,
    worst_case_chunk_text,
)

if TYPE_CHECKING:
    from onnxruntime import InferenceSession
    from tokenizers import Tokenizer

# The semantic index ranks by cosine distance over unit vectors, so every vector
# this module returns is L2 normalized whatever the model emits.
_MINIMUM_VECTOR_NORM = 1e-12
_VERIFICATION_TEXT = "pantaray"
# onnxruntime defaults to one thread per core. Indexing runs in the background
# while the person is using their machine, and a query arriving mid-index would
# otherwise start a second pool of that size, so the graph gets a small fixed
# budget and one caller at a time.
# Design limit: chosen from the production path on Apple silicon at the profile's
# chunk length; revisit if indexing throughput stops meeting the agreed gate.
INTRA_OP_THREADS = 2
INTER_OP_THREADS = 1


def pool_hidden_states(
    hidden_states: NDArray[numpy.float32],
    attention_mask: NDArray[numpy.int64],
    *,
    pooling: LocalEmbeddingPooling,
) -> NDArray[numpy.float32]:
    """Reduce per-token states to one unit vector per text."""
    if hidden_states.ndim != 3:
        raise LocalEmbeddingUnavailableError(
            "embedding model output is not a per-token sequence; "
            f"got rank {hidden_states.ndim}"
        )
    if pooling == "cls":
        pooled = hidden_states[:, 0, :]
    else:
        mask = attention_mask[:, :, None].astype(hidden_states.dtype)
        pooled = (hidden_states * mask).sum(axis=1) / numpy.clip(
            mask.sum(axis=1), 1, None
        )
    norms = numpy.linalg.norm(pooled, axis=1, keepdims=True)
    if bool((norms < _MINIMUM_VECTOR_NORM).any()):
        # Dividing by the clipped floor would turn a degenerate output into
        # arbitrary directions that the index would happily store.
        raise LocalEmbeddingUnavailableError(
            "embedding model produced a vector with no direction"
        )
    normalized: NDArray[numpy.float32] = pooled / norms
    return normalized


class LocalEmbeddingModel:
    """A loaded embedding model, shared by the whole process.

    onnxruntime sessions may be run from several threads, so the worker's
    projection thread and a search request share one loaded model.
    """

    def __init__(
        self,
        *,
        manifest: LocalEmbeddingManifest,
        tokenizer: Tokenizer,
        session: InferenceSession,
    ) -> None:
        self._manifest = manifest
        self._tokenizer = tokenizer
        self._session = session
        self._input_names = {entry.name for entry in session.get_inputs()}
        # The worker's indexing pass and a search request share this model.
        self._inference_lock = threading.Lock()

    @property
    def manifest(self) -> LocalEmbeddingManifest:
        return self._manifest

    def embed_query(self, text: str) -> tuple[float, ...]:
        return self._embed((self._manifest.query_prefix + text,))[0]

    def embed_documents(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        return self._embed(
            tuple(self._manifest.document_prefix + text for text in texts)
        )

    def _embed(self, texts: Sequence[str]) -> tuple[tuple[float, ...], ...]:
        if not texts:
            raise ValueError("embedding requires at least one text")
        return tuple(
            tuple(float(value) for value in vector) for vector in self._encode(texts)
        )

    def _encode(self, texts: Sequence[str]) -> NDArray[numpy.float32]:
        with self._inference_lock:
            return self._encode_serialized(texts)

    def _encode_serialized(self, texts: Sequence[str]) -> NDArray[numpy.float32]:
        encodings = self._tokenizer.encode_batch(list(texts))
        width = max(len(encoding.ids) for encoding in encodings)
        input_ids = numpy.zeros((len(encodings), width), dtype=numpy.int64)
        attention_mask = numpy.zeros((len(encodings), width), dtype=numpy.int64)
        for row, encoding in enumerate(encodings):
            # The mask comes from the tokenizer rather than from the id count: a
            # tokenizer that declares padding has already padded `ids`, and
            # treating that padding as content changes the vector.
            input_ids[row, : len(encoding.ids)] = encoding.ids
            attention_mask[row, : len(encoding.ids)] = encoding.attention_mask
        feeds: dict[str, NDArray[numpy.int64]] = {"input_ids": input_ids}
        if "attention_mask" in self._input_names:
            feeds["attention_mask"] = attention_mask
        if "token_type_ids" in self._input_names:
            feeds["token_type_ids"] = numpy.zeros_like(input_ids)
        hidden_states: NDArray[numpy.float32] = self._session.run(None, feeds)[0]
        return pool_hidden_states(
            hidden_states,
            attention_mask,
            pooling=self._manifest.pooling,
        )


def open_local_embedding_model(
    *,
    model_dir: Path,
    manifest: LocalEmbeddingManifest,
) -> LocalEmbeddingModel:
    """Load the tokenizer and the graph, then confirm what the manifest claims.

    Both the chunk length and the vector width are checked here, so a manifest
    that disagrees with its artifact is reported before any vector -- or any
    silently truncated chunk -- reaches the index.
    """
    import onnxruntime
    from tokenizers import Tokenizer

    try:
        tokenizer = Tokenizer.from_file(str(model_dir / manifest.tokenizer_file))
        tokenizer.enable_truncation(max_length=manifest.max_tokens)
        options = onnxruntime.SessionOptions()
        options.intra_op_num_threads = INTRA_OP_THREADS
        options.inter_op_num_threads = INTER_OP_THREADS
        session = onnxruntime.InferenceSession(
            str(model_dir / manifest.model_file),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
    # Neither library exposes a base class narrower than Exception for a
    # missing, malformed or unsupported artifact, which is the failure this
    # boundary owns and reports as an unusable model.
    except Exception as exc:
        raise LocalEmbeddingUnavailableError(
            f"embedding model could not be loaded: {model_dir}"
        ) from exc
    chunk = worst_case_chunk_text(manifest.max_text_chars)
    for prefix in (manifest.document_prefix, manifest.query_prefix):
        require_chunk_fits_window(
            token_count=len(tokenizer.encode(prefix + chunk).ids),
            manifest=manifest,
        )
    model = LocalEmbeddingModel(
        manifest=manifest,
        tokenizer=tokenizer,
        session=session,
    )
    width = len(model.embed_query(_VERIFICATION_TEXT))
    if width != manifest.dimensions:
        raise LocalEmbeddingUnavailableError(
            f"embedding model produces {width} dimensions, "
            f"manifest declares {manifest.dimensions}"
        )
    return model


__all__ = [
    "INTER_OP_THREADS",
    "INTRA_OP_THREADS",
    "LocalEmbeddingModel",
    "open_local_embedding_model",
    "pool_hidden_states",
]
