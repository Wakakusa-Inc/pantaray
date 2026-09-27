from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from pathlib import Path

from pantaray_agents.local_runtime.storage.sqlite_vector import (
    SQLiteVectorValueError,
    decode_float32_vector,
    encode_float32_vector,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .connection import open_memory_catalog_connection
from .embedding_chunks import (
    memory_embedding_chunk_at,
    validate_memory_embedding_chunk,
)
from .embedding_generations import (
    EmbeddingGeneration,
    generation_entry_table,
    generation_vector_table,
)
from .embedding_work import PendingMemoryEmbedding
from .fragments import content_sha256


class MemoryEmbeddingIndexUnavailableError(RuntimeError):
    """Raised when the semantic projection cannot be read safely."""


class MemoryEmbeddingValidationError(ValueError):
    def __init__(self, *, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


class MemoryEmbeddingProjectionStateError(RuntimeError):
    """Raised when projected data no longer matches its work item."""


def encode_embedding(vector: Sequence[float], *, dimensions: int) -> bytes:
    try:
        encoded: bytes = encode_float32_vector(vector, dimensions=dimensions)
        return encoded
    except SQLiteVectorValueError as exc:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_VECTOR_INVALID",
            message=str(exc),
        ) from exc


def decode_embedding(blob: bytes, *, dimensions: int) -> tuple[float, ...]:
    try:
        decoded: tuple[float, ...] = decode_float32_vector(
            blob,
            dimensions=dimensions,
        )
        return decoded
    except SQLiteVectorValueError as exc:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_VECTOR_INVALID",
            message=str(exc),
        ) from exc


def validate_pending_embedding(document: PendingMemoryEmbedding) -> None:
    try:
        validate_memory_embedding_chunk(
            fragment_content_text=document.fragment_content_text,
            fragment_content_sha256=document.fragment_content_sha256,
            chunk_index=document.chunk_index,
            chunk_content_sha256=document.chunk_content_sha256,
            max_text_chars=document.max_text_chars,
        )
    except ValueError as exc:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_CONTENT_HASH_INVALID",
            message=f"memory embedding source is invalid: {document.fragment_id}",
        ) from exc
    canonical_chunk = memory_embedding_chunk_at(
        document.fragment_content_text,
        chunk_index=document.chunk_index,
        max_text_chars=document.max_text_chars,
    )
    if canonical_chunk.content_text != document.content_text:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_CONTENT_HASH_INVALID",
            message=f"memory embedding chunk is invalid: {document.fragment_id}",
        )
    if content_sha256(document.content_text) != document.chunk_content_sha256:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_CONTENT_HASH_INVALID",
            message=f"memory embedding chunk hash is invalid: {document.fragment_id}",
        )
    if not document.content_text.strip():
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_CONTENT_EMPTY",
            message=f"memory fragment content is empty: {document.fragment_id}",
        )


def encode_embedding_vectors(
    vectors: Sequence[Sequence[float]],
    *,
    expected_count: int,
    generation: EmbeddingGeneration,
) -> tuple[bytes, ...]:
    """Check what the model produced against the generation it is indexed into.

    The model is loaded from the same manifest the generation was created from,
    so a disagreement here means the two drifted apart and the vectors must not
    reach the index.
    """
    if len(vectors) != expected_count:
        raise MemoryEmbeddingValidationError(
            error_code="MEMORY_EMBEDDING_RESPONSE_COUNT_INVALID",
            message="memory embedding count does not match the request",
        )
    return tuple(
        encode_embedding(vector, dimensions=generation.specification.dimensions)
        for vector in vectors
    )


def store_embedding_success(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    fragment_id: str,
    chunk_index: int,
    fragment_content_sha256: str,
    vector: Sequence[float],
    created_at: str,
    generation_id: int,
) -> None:
    document = _load_work_document(
        connection,
        user_id=user_id,
        fragment_id=fragment_id,
        chunk_index=chunk_index,
        generation_id=generation_id,
    )
    if document.fragment_content_sha256 != fragment_content_sha256:
        raise MemoryEmbeddingProjectionStateError(
            "memory embedding work no longer matches the fragment"
        )
    encoded = encode_embedding(vector, dimensions=document.dimensions)
    _store_encoded_embedding(
        connection,
        document=document,
        encoded_vector=encoded,
        created_at=created_at,
        allow_missing=False,
    )


def commit_embedding_projection_batch(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    documents: Sequence[PendingMemoryEmbedding],
    encoded_vectors: Sequence[bytes],
    created_at: str,
) -> int:
    if len(documents) != len(encoded_vectors):
        raise ValueError("documents and encoded_vectors must have the same length")
    for document in documents:
        validate_pending_embedding(document)
    for document, encoded in zip(documents, encoded_vectors, strict=True):
        decode_embedding(encoded, dimensions=document.dimensions)
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        with immediate_transaction(connection):
            return sum(
                _store_encoded_embedding(
                    connection,
                    document=document,
                    encoded_vector=encoded,
                    created_at=created_at,
                    allow_missing=True,
                )
                for document, encoded in zip(documents, encoded_vectors, strict=True)
            )


def _store_encoded_embedding(
    connection: sqlite3.Connection,
    *,
    document: PendingMemoryEmbedding,
    encoded_vector: bytes,
    created_at: str,
    allow_missing: bool,
) -> int:
    entries = generation_entry_table(document.generation_id)
    vectors = generation_vector_table(document.generation_id)
    if not _matches_current_fragment(connection, document=document):
        if allow_missing:
            return 0
        raise MemoryEmbeddingProjectionStateError(
            "memory embedding work no longer matches the fragment"
        )
    cursor = connection.execute(
        f"""
        INSERT INTO {entries}(
            user_id, generation_id, fragment_id, chunk_index, revision_id,
            fragment_content_sha256, chunk_content_sha256, created_at
        )
        SELECT fragments.user_id, work.generation_id, fragments.fragment_id,
               work.chunk_index, fragments.revision_id,
               fragments.content_sha256, ?, ?
        FROM memory_fragments AS fragments
        JOIN memory_embedding_work AS work
          ON work.user_id = fragments.user_id
         AND work.fragment_id = fragments.fragment_id
         AND work.generation_id = ?
         AND work.chunk_index = ?
         AND work.state = 'pending'
        WHERE fragments.user_id = ? AND fragments.fragment_id = ?
          AND fragments.revision_id = ? AND fragments.content_sha256 = ?
        """,
        (
            document.chunk_content_sha256,
            _require_non_empty(created_at, field_name="created_at"),
            document.generation_id,
            document.chunk_index,
            document.user_id,
            document.fragment_id,
            document.revision_id,
            document.fragment_content_sha256,
        ),
    )
    if cursor.rowcount == 0:
        if allow_missing:
            return 0
        raise MemoryEmbeddingProjectionStateError(
            "memory embedding work is missing or no longer matches the fragment"
        )
    if cursor.lastrowid is None:
        raise MemoryEmbeddingProjectionStateError(
            "memory embedding entry did not return an identifier"
        )
    embedding_id = cursor.lastrowid
    connection.execute(
        f"""
        INSERT INTO {vectors}(embedding_id, embedding, user_id, revision_id)
        VALUES (?, ?, ?, ?)
        """,
        (
            embedding_id,
            sqlite3.Binary(encoded_vector),
            document.user_id,
            document.revision_id,
        ),
    )
    deleted = connection.execute(
        """
        DELETE FROM memory_embedding_work
        WHERE user_id = ? AND generation_id = ? AND fragment_id = ?
          AND chunk_index = ?
          AND state = 'pending' AND attempt_count = ?
        """,
        (
            document.user_id,
            document.generation_id,
            document.fragment_id,
            document.chunk_index,
            document.attempt_count,
        ),
    ).rowcount
    if deleted != 1:
        raise MemoryEmbeddingProjectionStateError(
            "stored memory embedding could not finalize its work item"
        )
    return 1


def _matches_current_fragment(
    connection: sqlite3.Connection,
    *,
    document: PendingMemoryEmbedding,
) -> bool:
    row = connection.execute(
        """
        SELECT content_text, content_sha256
        FROM memory_fragments
        WHERE user_id = ? AND fragment_id = ? AND revision_id = ?
          AND content_sha256 = ?
        """,
        (
            document.user_id,
            document.fragment_id,
            document.revision_id,
            document.fragment_content_sha256,
        ),
    ).fetchone()
    if row is None:
        return False
    try:
        validate_memory_embedding_chunk(
            fragment_content_text=str(row[0]),
            fragment_content_sha256=str(row[1]),
            chunk_index=document.chunk_index,
            chunk_content_sha256=document.chunk_content_sha256,
            max_text_chars=document.max_text_chars,
        )
    except ValueError:
        return False
    return True


def _load_work_document(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    fragment_id: str,
    chunk_index: int,
    generation_id: int,
) -> PendingMemoryEmbedding:
    rows = connection.execute(
        """
        SELECT work.user_id, work.generation_id, work.chunk_index,
               work.attempt_count,
               fragments.fragment_id, fragments.revision_id,
               fragments.content_text, fragments.content_sha256,
               generations.profile_id, generations.model_id,
               generations.dimensions, generations.normalized,
               generations.max_text_chars
        FROM memory_embedding_work AS work
        JOIN memory_fragments AS fragments
          ON fragments.user_id = work.user_id
         AND fragments.fragment_id = work.fragment_id
        JOIN memory_embedding_generations AS generations
          ON generations.generation_id = work.generation_id
        WHERE work.user_id = ? AND work.fragment_id = ?
          AND work.chunk_index = ?
          AND work.state = 'pending' AND work.generation_id = ?
        """,
        (user_id, fragment_id, chunk_index, generation_id),
    ).fetchall()
    if len(rows) != 1:
        raise MemoryEmbeddingProjectionStateError(
            "memory embedding work is missing or generation is ambiguous"
        )
    row = rows[0]
    fragment_content_text = str(row[6])
    chunk = memory_embedding_chunk_at(
        fragment_content_text,
        chunk_index=int(row[2]),
        max_text_chars=int(row[12]),
    )
    return PendingMemoryEmbedding(
        user_id=str(row[0]),
        generation_id=int(row[1]),
        chunk_index=int(row[2]),
        attempt_count=int(row[3]),
        fragment_id=str(row[4]),
        revision_id=str(row[5]),
        fragment_content_text=fragment_content_text,
        content_text=chunk.content_text,
        fragment_content_sha256=str(row[7]),
        chunk_content_sha256=chunk.content_sha256,
        profile_id=str(row[8]),
        model_id=str(row[9]),
        dimensions=int(row[10]),
        normalized=bool(row[11]),
        max_text_chars=int(row[12]),
    )


def _require_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


__all__ = [
    "MemoryEmbeddingIndexUnavailableError",
    "MemoryEmbeddingProjectionStateError",
    "MemoryEmbeddingValidationError",
    "commit_embedding_projection_batch",
    "decode_embedding",
    "encode_embedding",
    "encode_embedding_vectors",
    "store_embedding_success",
    "validate_pending_embedding",
]
