from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from .artifact_block_fts import rebuild_memory_artifact_blocks_fts
from .migrations import MigrationError

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
FTS_JOB_STATUS_RUNNING = "running"
FTS_JOB_STATUS_COMPLETED = "completed"
FTS_JOB_STATUS_FAILED = "failed"
FTS_JOB_STATUS_PENDING = "queued"
FTS_TARGET_TABLE_MEMORY_ARTIFACT_BLOCKS = "memory_artifact_blocks_fts"


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def _validate_busy_timeout(busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")


def rebuild_memory_artifact_fts_projection(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> str:
    _validate_busy_timeout(busy_timeout_ms)
    fts_job_id = str(uuid.uuid4())

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                INSERT INTO fts_jobs(
                    fts_job_id,
                    target_table,
                    status,
                    enqueued_at,
                    started_at
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
                """,
                (
                    fts_job_id,
                    FTS_TARGET_TABLE_MEMORY_ARTIFACT_BLOCKS,
                    FTS_JOB_STATUS_RUNNING,
                ),
            )

    try:
        rebuild_memory_artifact_blocks_fts(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    except sqlite3.DatabaseError as exc:
        with sqlite3.connect(db_path) as connection:
            _configure_connection(
                connection=connection, busy_timeout_ms=busy_timeout_ms
            )
            with connection:
                connection.execute(
                    """
                    UPDATE fts_jobs
                    SET status = ?,
                        completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE fts_job_id = ?
                    """,
                    (FTS_JOB_STATUS_FAILED, fts_job_id),
                )
        raise MigrationError(
            "failed to rebuild memory artifact FTS projection"
        ) from exc

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                UPDATE fts_jobs
                SET status = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE fts_job_id = ?
                """,
                (FTS_JOB_STATUS_COMPLETED, fts_job_id),
            )
    return fts_job_id


def enqueue_fts_rebuild_job(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> str:
    _validate_busy_timeout(busy_timeout_ms)
    fts_job_id = str(uuid.uuid4())

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                INSERT INTO fts_jobs(
                    fts_job_id,
                    target_table,
                    status,
                    enqueued_at
                ) VALUES (
                    ?,
                    ?,
                    ?,
                    strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                )
                """,
                (
                    fts_job_id,
                    FTS_TARGET_TABLE_MEMORY_ARTIFACT_BLOCKS,
                    FTS_JOB_STATUS_PENDING,
                ),
            )
    return fts_job_id


def run_next_pending_fts_rebuild_job(*, db_path: Path, busy_timeout_ms: int) -> bool:
    _validate_busy_timeout(busy_timeout_ms)

    job_row: str | None = None
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            row = connection.execute(
                """
                SELECT fts_job_id
                FROM fts_jobs
                WHERE status = ?
                ORDER BY enqueued_at ASC
                LIMIT 1
                """,
                (FTS_JOB_STATUS_PENDING,),
            ).fetchone()
            if row is None:
                return False

            update_cursor = connection.execute(
                """
                UPDATE fts_jobs
                SET status = ?,
                    started_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE fts_job_id = ? AND status = ?
                """,
                (FTS_JOB_STATUS_RUNNING, str(row[0]), FTS_JOB_STATUS_PENDING),
            )
            if update_cursor.rowcount <= 0:
                return False

            job_row = str(row[0])

    if job_row is None:
        return False

    fts_job_id = job_row
    try:
        rebuild_memory_artifact_blocks_fts(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    except sqlite3.DatabaseError as exc:
        with sqlite3.connect(db_path) as connection:
            _configure_connection(
                connection=connection, busy_timeout_ms=busy_timeout_ms
            )
            with connection:
                connection.execute(
                    """
                    UPDATE fts_jobs
                    SET status = ?,
                        completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                    WHERE fts_job_id = ?
                    """,
                    (FTS_JOB_STATUS_FAILED, fts_job_id),
                )
        raise MigrationError(
            "failed to rebuild memory artifact FTS projection"
        ) from exc

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                UPDATE fts_jobs
                SET status = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE fts_job_id = ?
                """,
                (FTS_JOB_STATUS_COMPLETED, fts_job_id),
            )
    return True
