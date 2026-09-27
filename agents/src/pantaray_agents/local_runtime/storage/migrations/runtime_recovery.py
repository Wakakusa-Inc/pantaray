from __future__ import annotations

import sqlite3
import uuid
from pathlib import Path

from .connection import configure_connection, ensure_meta_tables
from .constants import INFLIGHT_JOB_STATUSES, JOB_STATUS_QUEUED
from .specs import MigrationError


def repair_inflight_jobs_for_startup(db_path: Path, busy_timeout_ms: int) -> int:
    _validate_busy_timeout(busy_timeout_ms)
    placeholders = ", ".join("?" for _ in INFLIGHT_JOB_STATUSES)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                f"""
                UPDATE job_attempts
                SET
                    status = 'failed',
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    error_code = COALESCE(error_code, 'RECOVERY_REQUEUED'),
                    error_message = COALESCE(
                        error_message,
                        'Worker restart re-queued the in-flight job'
                    )
                WHERE status = 'running'
                  AND job_id IN (
                    SELECT job_id
                    FROM jobs
                    WHERE status IN ({placeholders})
                  )
                """,
                INFLIGHT_JOB_STATUSES,
            )
            connection.execute(
                f"""
                UPDATE processes
                SET
                    status = 'enqueued',
                    current_job_id = NULL,
                    heartbeat_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
                WHERE process_id IN (
                    SELECT process_id
                    FROM jobs
                    WHERE status IN ({placeholders})
                      AND process_id IS NOT NULL
                )
                """,
                INFLIGHT_JOB_STATUSES,
            )
            cursor = connection.execute(
                f"""
                UPDATE jobs
                SET
                    status = ?,
                    claimed_by = NULL,
                    claimed_at = NULL,
                    heartbeat_at = NULL
                WHERE status IN ({placeholders})
                """,
                (JOB_STATUS_QUEUED, *INFLIGHT_JOB_STATUSES),
            )
        return int(cursor.rowcount if cursor.rowcount >= 0 else 0)


def record_runtime_recovery_run(db_path: Path, busy_timeout_ms: int, note: str) -> str:
    _validate_busy_timeout(busy_timeout_ms)
    if not note.strip():
        raise MigrationError("runtime recovery note must not be empty")
    recovery_run_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        ensure_meta_tables(connection)
        with connection:
            connection.execute(
                """
                INSERT INTO runtime_recovery_runs(
                    recovery_run_id,
                    status,
                    note
                ) VALUES (?, ?, ?)
                """,
                (recovery_run_id, "completed", note),
            )
    return recovery_run_id


def _validate_busy_timeout(busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")


__all__ = ["record_runtime_recovery_run", "repair_inflight_jobs_for_startup"]
