from __future__ import annotations

import sqlite3
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.local_runtime.storage.transactions import immediate_transaction

from .connection import open_memory_catalog_connection
from .embedding_chunks import memory_embedding_chunk_at
from .embedding_generation_storage import require_generation_id
from .embedding_generations import EmbeddingGeneration, EmbeddingSpecification

# One chunk per inference: the local model runs on the user's CPU alongside the
# rest of the app, and a batch of one never pads a short chunk out to the length
# of the longest one in the batch.
MEMORY_EMBEDDING_BATCH_SIZE = 1


@dataclass(frozen=True, slots=True)
class PendingMemoryEmbedding:
    user_id: str
    generation_id: int
    fragment_id: str
    chunk_index: int
    revision_id: str
    fragment_content_text: str
    content_text: str
    fragment_content_sha256: str
    chunk_content_sha256: str
    attempt_count: int
    profile_id: str
    model_id: str
    dimensions: int
    normalized: bool
    max_text_chars: int

    @property
    def generation(self) -> EmbeddingGeneration:
        return EmbeddingGeneration(
            generation_id=self.generation_id,
            specification=EmbeddingSpecification(
                model_id=self.model_id,
                dimensions=self.dimensions,
                normalized=self.normalized,
                max_text_chars=self.max_text_chars,
                profile_id=self.profile_id,
            ),
        )


def claim_due_embeddings(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    generation_id: int,
    now: str,
    limit: int = MEMORY_EMBEDDING_BATCH_SIZE,
) -> tuple[PendingMemoryEmbedding, ...]:
    """Claim work for exactly one generation.

    The caller has already resolved which generation the installed model builds.
    Claiming from any other one would embed with this model and store the vector
    under a generation built by a different artifact, which no later check would
    notice.
    """
    if limit <= 0 or limit > MEMORY_EMBEDDING_BATCH_SIZE:
        raise ValueError(f"limit must be between 1 and {MEMORY_EMBEDDING_BATCH_SIZE}")
    normalized_user_id = _require_non_empty(user_id, field_name="user_id")
    normalized_now = _require_non_empty(now, field_name="now")
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        with immediate_transaction(connection):
            rows = connection.execute(
                """
                SELECT work.user_id, work.generation_id, work.fragment_id,
                       work.chunk_index, work.attempt_count,
                       fragments.revision_id, fragments.content_text,
                       fragments.content_sha256,
                       generations.profile_id, generations.model_id,
                       generations.dimensions, generations.normalized,
                       generations.max_text_chars
                FROM memory_embedding_work AS work
                JOIN memory_fragments AS fragments
                  ON fragments.user_id = work.user_id
                 AND fragments.fragment_id = work.fragment_id
                JOIN memory_embedding_generations AS generations
                  ON generations.generation_id = work.generation_id
                WHERE work.user_id = ? AND work.generation_id = ?
                  AND (
                    work.state = 'pending'
                    OR (work.state = 'retry_wait' AND work.next_attempt_at <= ?)
                  )
                ORDER BY work.created_at, work.fragment_id, work.chunk_index
                LIMIT ?
                """,
                (
                    normalized_user_id,
                    require_generation_id(generation_id),
                    normalized_now,
                    limit,
                ),
            ).fetchall()
            return _claim_rows(
                connection,
                rows=rows,
                now=normalized_now,
            )


def _claim_rows(
    connection: sqlite3.Connection,
    *,
    rows: Sequence[sqlite3.Row | tuple[object, ...]],
    now: str,
) -> tuple[PendingMemoryEmbedding, ...]:
    claimed: list[PendingMemoryEmbedding] = []
    for row in rows:
        updated = connection.execute(
            """
            UPDATE memory_embedding_work
            SET state = 'pending', attempt_count = attempt_count + 1,
                next_attempt_at = NULL, last_error_code = NULL, updated_at = ?
            WHERE user_id = ? AND generation_id = ? AND fragment_id = ?
              AND chunk_index = ?
              AND (
                state = 'pending'
                OR (state = 'retry_wait' AND next_attempt_at <= ?)
              )
            """,
            (
                now,
                str(row[0]),
                _db_int(row[1]),
                str(row[2]),
                _db_int(row[3]),
                now,
            ),
        ).rowcount
        if updated != 1:
            continue
        chunk = memory_embedding_chunk_at(
            str(row[6]),
            chunk_index=_db_int(row[3]),
            max_text_chars=_db_int(row[12]),
        )
        claimed.append(
            PendingMemoryEmbedding(
                user_id=str(row[0]),
                generation_id=_db_int(row[1]),
                fragment_id=str(row[2]),
                chunk_index=_db_int(row[3]),
                attempt_count=_db_int(row[4]) + 1,
                revision_id=str(row[5]),
                fragment_content_text=str(row[6]),
                content_text=chunk.content_text,
                fragment_content_sha256=str(row[7]),
                chunk_content_sha256=chunk.content_sha256,
                profile_id=str(row[8]),
                model_id=str(row[9]),
                dimensions=_db_int(row[10]),
                normalized=_db_bool(row[11]),
                max_text_chars=_db_int(row[12]),
            )
        )
    return tuple(claimed)


def mark_embedding_work_failed(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    documents: Sequence[PendingMemoryEmbedding],
    error_code: str,
    updated_at: str,
) -> int:
    """Record chunks the local model will never be able to embed.

    Every remaining failure is a property of the chunk itself -- content that no
    longer matches its fragment, or a vector the index cannot store -- so none
    of them is worth attempting again with the same input.
    """
    normalized_error = _require_non_empty(error_code, field_name="error_code")
    failed_count = 0
    with open_memory_catalog_connection(
        db_path=db_path, busy_timeout_ms=busy_timeout_ms
    ) as connection:
        with immediate_transaction(connection):
            for document in documents:
                failed_count += connection.execute(
                    """
                    UPDATE memory_embedding_work
                    SET state = 'failed', next_attempt_at = NULL,
                        last_error_code = ?, updated_at = ?
                    WHERE user_id = ? AND generation_id = ? AND fragment_id = ?
                      AND chunk_index = ?
                      AND state = 'pending' AND attempt_count = ?
                    """,
                    (
                        normalized_error,
                        updated_at,
                        document.user_id,
                        document.generation_id,
                        document.fragment_id,
                        document.chunk_index,
                        document.attempt_count,
                    ),
                ).rowcount
    return failed_count


def _require_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must not be empty")
    return normalized


def _db_int(value: object) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("memory embedding work integer column is invalid")
    return value


def _db_bool(value: object) -> bool:
    if value not in (0, 1) or isinstance(value, bool):
        raise TypeError("memory embedding work boolean column is invalid")
    return bool(value)


__all__ = [
    "MEMORY_EMBEDDING_BATCH_SIZE",
    "PendingMemoryEmbedding",
    "claim_due_embeddings",
    "mark_embedding_work_failed",
]
