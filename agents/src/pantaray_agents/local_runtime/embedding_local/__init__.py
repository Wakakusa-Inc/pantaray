"""Local embedding: the bundled model that indexes and searches memory.

The model is loaded once per process. Because the desktop app materialises the
model directory before it starts the runtime, an absent or mismatched model
stays unavailable until the runtime restarts rather than being retried on every
search.
"""

from __future__ import annotations

import logging
import threading

from .manifest import (
    LOCAL_EMBEDDING_MANIFEST_FILENAME,
    LOCAL_EMBEDDING_MODEL_DIR_ENV,
    WORST_CASE_CHUNK_UNIT,
    LocalEmbeddingManifest,
    LocalEmbeddingPooling,
    LocalEmbeddingUnavailableError,
    artifact_revision_digest,
    file_sha256,
    load_verified_manifest,
    read_local_embedding_model_dir,
    require_chunk_fits_window,
    worst_case_chunk_text,
)
from .runner import LocalEmbeddingModel, open_local_embedding_model, pool_hidden_states

logger = logging.getLogger(__name__)

_LOAD_LOCK = threading.Lock()
_LOAD_OUTCOME: LocalEmbeddingModel | LocalEmbeddingUnavailableError | None = None


def load_local_embedding_model() -> LocalEmbeddingModel:
    """The process-wide embedding model.

    Raises `LocalEmbeddingUnavailableError` when the model is not installed or
    does not match its manifest; callers report that as `provider_unavailable`.
    """
    global _LOAD_OUTCOME
    with _LOAD_LOCK:
        if _LOAD_OUTCOME is None:
            _LOAD_OUTCOME = _load()
        outcome = _LOAD_OUTCOME
    if isinstance(outcome, LocalEmbeddingUnavailableError):
        raise LocalEmbeddingUnavailableError(str(outcome)) from outcome
    return outcome


def reset_local_embedding_model_cache() -> None:
    """Drop the loaded model so the next call reads the model directory again."""
    global _LOAD_OUTCOME
    with _LOAD_LOCK:
        _LOAD_OUTCOME = None


def _load() -> LocalEmbeddingModel | LocalEmbeddingUnavailableError:
    try:
        model_dir = read_local_embedding_model_dir()
        manifest = load_verified_manifest(model_dir)
        model = open_local_embedding_model(model_dir=model_dir, manifest=manifest)
    except LocalEmbeddingUnavailableError as exc:
        logger.warning(
            "local embedding model is unavailable; semantic memory search is off: %s",
            exc,
        )
        return exc
    # Callers treat this as "there is no usable model", not as a reason to fail
    # startup, so anything the artifact or the machine throws is converted here
    # rather than escaping into the runtime's own error paths.
    except Exception as exc:
        logger.warning(
            "local embedding model could not be loaded; semantic memory search is off",
            exc_info=True,
        )
        return LocalEmbeddingUnavailableError(
            f"embedding model could not be loaded: {type(exc).__name__}"
        )
    logger.info(
        "local embedding model loaded",
        extra={
            "embedding_profile_id": manifest.profile_id,
            "embedding_model_id": manifest.model_id,
        },
    )
    return model


__all__ = [
    "LOCAL_EMBEDDING_MANIFEST_FILENAME",
    "LOCAL_EMBEDDING_MODEL_DIR_ENV",
    "WORST_CASE_CHUNK_UNIT",
    "LocalEmbeddingManifest",
    "LocalEmbeddingModel",
    "LocalEmbeddingPooling",
    "LocalEmbeddingUnavailableError",
    "artifact_revision_digest",
    "file_sha256",
    "load_local_embedding_model",
    "load_verified_manifest",
    "open_local_embedding_model",
    "pool_hidden_states",
    "read_local_embedding_model_dir",
    "require_chunk_fits_window",
    "reset_local_embedding_model_cache",
    "worst_case_chunk_text",
]
