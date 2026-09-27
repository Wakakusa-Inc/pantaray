"""The bundled embedding model's manifest: its identity and its integrity.

Nothing here knows which model is bundled. Every model-specific value -- the
model id, the artifact revision, the digests, the dimensions, the token window,
the pooling and the query/document prefixes -- is read from the manifest that
ships beside the model files, so replacing the model is a matter of preparing
new files and a new manifest.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

LOCAL_EMBEDDING_MODEL_DIR_ENV = "LOCAL_EMBEDDING_MODEL_DIR"
LOCAL_EMBEDDING_MANIFEST_FILENAME = "manifest.json"
ARTIFACT_REVISION_HEX_CHARS = 16
_DIGEST_READ_CHUNK_BYTES = 1 << 20
# A memory fragment is split into chunks by character count, because the same
# split is computed in SQL when embedding work is enqueued and has to hold
# whether or not the model is installed. How many characters fit in the token
# window is a property of the tokenizer, so `max_text_chars` is measured when
# the artifact is prepared and re-checked when it is loaded, against a chunk of
# dense Japanese carrying characters the vocabulary does not cover.
#
# Design limit: content even denser than this probe -- a chunk of nothing but
# emoji -- is truncated at the window rather than rejected. Raise the probe's
# density if real memory documents ever look like that.
WORST_CASE_CHUNK_UNIT = "記憶検索の設計と実装の記録。𩸽𠮷"

type LocalEmbeddingPooling = Literal["mean", "cls"]


class LocalEmbeddingUnavailableError(RuntimeError):
    """Raised when the bundled embedding model cannot be used.

    Semantic memory search reports this as `provider_unavailable`, which is
    distinct from a search that ran and found nothing.
    """


class LocalEmbeddingManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        protected_namespaces=(),
    )

    model_id: str = Field(min_length=1, pattern=r"\S")
    source_revision: str = Field(min_length=1, pattern=r"\S")
    model_slug: str = Field(pattern=r"^[a-z0-9][a-z0-9.-]*$")
    artifact_revision: str = Field(
        pattern=rf"^[0-9a-f]{{{ARTIFACT_REVISION_HEX_CHARS}}}$"
    )
    model_file: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    model_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    tokenizer_file: str = Field(pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    tokenizer_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    dimensions: int = Field(gt=0)
    max_tokens: int = Field(gt=0)
    max_text_chars: int = Field(gt=0)
    pooling: LocalEmbeddingPooling
    query_prefix: str
    document_prefix: str

    @property
    def profile_id(self) -> str:
        """The memory embedding profile this artifact produces vectors for.

        The revision is part of the id, so any change to the model files or to
        the preprocessing starts a new generation instead of mixing new vectors
        into an index built by the previous artifact.
        """
        return (
            f"memory.local.{self.model_slug}.{self.dimensions}.{self.artifact_revision}"
        )


def artifact_revision_digest(
    *,
    model_id: str,
    source_revision: str,
    model_slug: str,
    model_file: str,
    model_sha256: str,
    tokenizer_file: str,
    tokenizer_sha256: str,
    dimensions: int,
    max_tokens: int,
    max_text_chars: int,
    pooling: str,
    query_prefix: str,
    document_prefix: str,
) -> str:
    """The revision that identifies exactly this artifact and preprocessing.

    The preparation script writes it and the runtime recomputes it, so a
    manifest edited without rebuilding -- a changed prefix or token window
    against an unchanged revision -- is refused instead of silently projecting
    incompatible vectors into an existing generation.
    """
    identity = json.dumps(
        {
            "model_id": model_id,
            "source_revision": source_revision,
            "model_slug": model_slug,
            "model_file": model_file,
            "model_sha256": model_sha256,
            "tokenizer_file": tokenizer_file,
            "tokenizer_sha256": tokenizer_sha256,
            "dimensions": dimensions,
            "max_tokens": max_tokens,
            "max_text_chars": max_text_chars,
            "pooling": pooling,
            "query_prefix": query_prefix,
            "document_prefix": document_prefix,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(identity).hexdigest()[:ARTIFACT_REVISION_HEX_CHARS]


def worst_case_chunk_text(max_text_chars: int) -> str:
    """A chunk of the given length that is expensive for a tokenizer."""
    if max_text_chars <= 0:
        raise ValueError("max_text_chars must be positive")
    repeats = -(-max_text_chars // len(WORST_CASE_CHUNK_UNIT))
    return (WORST_CASE_CHUNK_UNIT * repeats)[:max_text_chars]


def require_chunk_fits_window(
    *, token_count: int, manifest: LocalEmbeddingManifest
) -> None:
    """Refuse an artifact whose chunk length can overflow its token window.

    Beyond the window the tokenizer truncates, and the tail of the chunk would
    never reach the index while nothing reported it.
    """
    if token_count > manifest.max_tokens:
        raise LocalEmbeddingUnavailableError(
            f"a chunk of {manifest.max_text_chars} characters takes "
            f"{token_count} tokens, past the window of {manifest.max_tokens}"
        )


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(_DIGEST_READ_CHUNK_BYTES):
            digest.update(chunk)
    return digest.hexdigest()


def read_local_embedding_model_dir() -> Path:
    """The directory the desktop app materialises the model into.

    Its absence means semantic search is unavailable, not that the runtime is
    misconfigured, so this reports it as such rather than failing startup.
    """
    raw = os.getenv(LOCAL_EMBEDDING_MODEL_DIR_ENV)
    if raw is None or not raw.strip():
        raise LocalEmbeddingUnavailableError(
            f"{LOCAL_EMBEDDING_MODEL_DIR_ENV} is not set"
        )
    return Path(raw).expanduser()


def load_verified_manifest(model_dir: Path) -> LocalEmbeddingManifest:
    """Parse the manifest and verify that it describes the files on disk."""
    manifest_path = model_dir / LOCAL_EMBEDDING_MANIFEST_FILENAME
    try:
        document = manifest_path.read_text("utf-8")
    except OSError as exc:
        raise LocalEmbeddingUnavailableError(
            f"embedding model manifest is unreadable: {manifest_path}"
        ) from exc
    try:
        manifest = LocalEmbeddingManifest.model_validate_json(document)
    except ValidationError as exc:
        raise LocalEmbeddingUnavailableError(
            f"embedding model manifest is invalid: {manifest_path}"
        ) from exc
    expected_revision = artifact_revision_digest(
        # Every field except the revision itself takes part, so a field added to
        # the manifest without being added to the digest fails here.
        **manifest.model_dump(exclude={"artifact_revision"})
    )
    if expected_revision != manifest.artifact_revision:
        raise LocalEmbeddingUnavailableError(
            "embedding model manifest revision does not match its contents: "
            f"{manifest_path}"
        )
    for filename, expected_digest in (
        (manifest.model_file, manifest.model_sha256),
        (manifest.tokenizer_file, manifest.tokenizer_sha256),
    ):
        path = model_dir / filename
        try:
            actual_digest = file_sha256(path)
        except OSError as exc:
            raise LocalEmbeddingUnavailableError(
                f"embedding model file is unreadable: {path}"
            ) from exc
        if actual_digest != expected_digest:
            raise LocalEmbeddingUnavailableError(
                f"embedding model file does not match its manifest digest: {path}"
            )
    return manifest


__all__ = [
    "ARTIFACT_REVISION_HEX_CHARS",
    "LOCAL_EMBEDDING_MANIFEST_FILENAME",
    "LOCAL_EMBEDDING_MODEL_DIR_ENV",
    "WORST_CASE_CHUNK_UNIT",
    "LocalEmbeddingManifest",
    "LocalEmbeddingPooling",
    "LocalEmbeddingUnavailableError",
    "artifact_revision_digest",
    "file_sha256",
    "load_verified_manifest",
    "read_local_embedding_model_dir",
    "require_chunk_fits_window",
    "worst_case_chunk_text",
]
