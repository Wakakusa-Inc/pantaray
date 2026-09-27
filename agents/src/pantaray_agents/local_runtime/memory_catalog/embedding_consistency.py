from __future__ import annotations

import sqlite3

from .embedding_chunks import split_memory_embedding_chunks
from .fragments import content_sha256

# A chunk only reaches 'failed' when this model cannot embed it and retrying the
# same input would not change that. Counting those as unfinished would keep the
# generation from ever activating, which switches semantic search off entirely
# for one unusable chunk, so a failed chunk is excluded from the generation's
# expected coverage instead.
UNEMBEDDABLE_CHUNK_SQL = "state = 'failed'"


class MemoryEmbeddingConsistencyError(RuntimeError):
    """Raised when a generation does not exactly cover canonical fragments."""


def verify_embedding_generation_complete(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    generation_id: int,
    entries: str,
    vectors: str,
) -> None:
    generation_row = connection.execute(
        """
        SELECT max_text_chars
        FROM memory_embedding_generations
        WHERE generation_id = ?
        """,
        (generation_id,),
    ).fetchone()
    if generation_row is None:
        raise MemoryEmbeddingConsistencyError("embedding generation does not exist")
    expected = _expected_chunks(
        connection,
        user_id=user_id,
        max_text_chars=int(generation_row[0]),
    )
    has_unfinished_work = has_unfinished_embedding_work(
        connection,
        user_id=user_id,
        generation_id=generation_id,
    )
    unembeddable = {
        (str(row[0]), int(row[1]))
        for row in connection.execute(
            f"""
            SELECT fragment_id, chunk_index
            FROM memory_embedding_work
            WHERE user_id = ? AND generation_id = ? AND {UNEMBEDDABLE_CHUNK_SQL}
            """,
            (user_id, generation_id),
        ).fetchall()
    }
    entry_rows = connection.execute(
        f"""
        SELECT fragment_id, chunk_index, revision_id,
               fragment_content_sha256, chunk_content_sha256
        FROM {entries}
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchall()
    actual = {
        (str(row[0]), int(row[1])): (str(row[2]), str(row[3]), str(row[4]))
        for row in entry_rows
    }
    vector_counts = connection.execute(
        f"""
        SELECT COUNT(*),
               SUM(CASE WHEN entries.embedding_id IS NOT NULL THEN 1 ELSE 0 END)
        FROM {vectors} AS vectors
        LEFT JOIN {entries} AS entries
          ON entries.embedding_id = vectors.embedding_id
         AND entries.user_id = vectors.user_id
         AND entries.revision_id = vectors.revision_id
        WHERE vectors.user_id = ?
        """,
        (user_id,),
    ).fetchone()
    vector_total = int(vector_counts[0])
    vector_linked = int(vector_counts[1] or 0)
    actual_keys = set(actual)
    has_stale_projection = any(
        expected.get(key) != metadata for key, metadata in actual.items()
    )
    if (
        has_unfinished_work
        or has_stale_projection
        or bool(actual_keys & unembeddable)
        or actual_keys | unembeddable != set(expected)
        or vector_total != len(actual)
        or vector_linked != len(actual)
    ):
        raise MemoryEmbeddingConsistencyError(
            "embedding generation is incomplete or inconsistent"
        )


def has_unfinished_embedding_work(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    generation_id: int,
) -> bool:
    row = connection.execute(
        f"""
        SELECT EXISTS(
            SELECT 1 FROM memory_embedding_work
            WHERE user_id = ? AND generation_id = ? AND NOT {UNEMBEDDABLE_CHUNK_SQL}
        )
        """,
        (user_id, generation_id),
    ).fetchone()
    return bool(row[0])


def _expected_chunks(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    max_text_chars: int,
) -> dict[tuple[str, int], tuple[str, str, str]]:
    rows = connection.execute(
        """
        SELECT fragment_id, revision_id, content_text, content_sha256
        FROM memory_fragments
        WHERE user_id = ?
          AND block_kind NOT IN ('record_root', 'document_root')
        """,
        (user_id,),
    ).fetchall()
    expected: dict[tuple[str, int], tuple[str, str, str]] = {}
    for row in rows:
        fragment_id = str(row[0])
        revision_id = str(row[1])
        content_text = str(row[2])
        fragment_hash = str(row[3])
        if content_sha256(content_text) != fragment_hash:
            raise MemoryEmbeddingConsistencyError(
                "canonical memory fragment content hash is invalid"
            )
        for chunk in split_memory_embedding_chunks(
            content_text,
            max_text_chars=max_text_chars,
        ):
            expected[(fragment_id, chunk.chunk_index)] = (
                revision_id,
                fragment_hash,
                chunk.content_sha256,
            )
    return expected


__all__ = [
    "MemoryEmbeddingConsistencyError",
    "UNEMBEDDABLE_CHUNK_SQL",
    "has_unfinished_embedding_work",
    "verify_embedding_generation_complete",
]
