from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .migrations import MigrationError

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
DEFAULT_SEARCH_LIMIT = 20
MAX_SEARCH_LIMIT = 100


@dataclass(frozen=True)
class ArtifactBlockSearchResult:
    block_id: str
    artifact_id: str
    block_seq: int
    snippet_text: str


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def _validate_busy_timeout(busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")


def _validate_query(query: str) -> str:
    normalized = query.strip()
    if not normalized:
        raise MigrationError("search query must not be empty")
    return normalized


def _validate_limit(limit: int) -> int:
    if limit <= 0:
        raise MigrationError("search limit must be a positive integer")
    if limit > MAX_SEARCH_LIMIT:
        raise MigrationError(
            f"search limit must be less than or equal to {MAX_SEARCH_LIMIT}"
        )
    return limit


def rebuild_memory_artifact_blocks_fts(*, db_path: Path, busy_timeout_ms: int) -> int:
    _validate_busy_timeout(busy_timeout_ms)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                "INSERT INTO memory_artifact_blocks_fts(memory_artifact_blocks_fts) VALUES('rebuild');"
            )
            row = connection.execute(
                "SELECT count(*) FROM memory_artifact_blocks_fts;"
            ).fetchone()
    if row is None:
        return 0
    return int(row[0])


def search_memory_artifact_blocks(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    query: str,
    limit: int = DEFAULT_SEARCH_LIMIT,
) -> tuple[ArtifactBlockSearchResult, ...]:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_query = _validate_query(query)
    normalized_limit = _validate_limit(limit)

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        rows = connection.execute(
            """
            SELECT
                blocks.block_id,
                files.artifact_id,
                blocks.block_index,
                snippet(memory_artifact_blocks_fts, 0, '<mark>', '</mark>', '…', 10) AS snippet_text
            FROM memory_artifact_blocks_fts
            JOIN memory_artifact_blocks AS blocks
                ON blocks.block_rowid = memory_artifact_blocks_fts.rowid
            JOIN memory_artifact_files AS files
                ON files.file_id = blocks.file_id
            WHERE memory_artifact_blocks_fts MATCH ?
            ORDER BY bm25(memory_artifact_blocks_fts)
            LIMIT ?
            """,
            (normalized_query, normalized_limit),
        ).fetchall()

    return tuple(
        ArtifactBlockSearchResult(
            block_id=str(row[0]),
            artifact_id=str(row[1]),
            block_seq=int(row[2]),
            snippet_text=str(row[3]),
        )
        for row in rows
    )
