from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

_SCHEDULER_RESTART_ERROR_CODE = "SCHEDULER_PROCESS_RESTARTED"


def recover_interrupted_activity_summary_scheduler_runs(
    *,
    db_path: Path | str,
    busy_timeout_ms: int,
    recovered_at: datetime | None = None,
) -> int:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    completed_at = _iso_z(datetime.now(UTC) if recovered_at is None else recovered_at)
    error_details_json = json.dumps(
        {"message": "Activity Summary scheduler process restarted"},
        ensure_ascii=False,
    )
    with sqlite3.connect(str(db_path)) as connection:
        configure_connection(connection, busy_timeout_ms)
        connection.execute("BEGIN IMMEDIATE")
        try:
            cursor = connection.execute(
                """
                UPDATE scheduler_job_runs
                SET status = 'failed', error_code = ?, error_details_json = ?,
                    completed_at = ?
                WHERE status = 'running'
                  AND job_name IN (
                      SELECT job_name
                      FROM scheduler_jobs
                      WHERE job_kind = 'activity_summary'
                  )
                """,
                (
                    _SCHEDULER_RESTART_ERROR_CODE,
                    error_details_json,
                    completed_at,
                ),
            )
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return max(cursor.rowcount, 0)


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


__all__ = ["recover_interrupted_activity_summary_scheduler_runs"]
