from __future__ import annotations

import sqlite3
from typing import TypedDict

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)


class LocalJobRef(TypedDict):
    job_id: str
    process_id: str
    status: str
    scheduled_at: str


def read_local_job_payload_json(
    *,
    db_path: str,
    busy_timeout_ms: int,
    job_id: str,
) -> str | None:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        row = connection.execute(
            "SELECT payload_json FROM job_payloads WHERE job_id = ?",
            (job_id,),
        ).fetchone()
    if row is None or row[0] is None:
        return None
    return str(row[0])


def read_local_job_ref_by_type_and_logical_key(
    *,
    db_path: str,
    busy_timeout_ms: int,
    job_type: str,
    logical_key: str,
) -> LocalJobRef | None:
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        row = connection.execute(
            """
            SELECT job_id, process_id, status, scheduled_at
            FROM jobs
            WHERE job_type = ? AND logical_key = ?
            ORDER BY scheduled_at DESC
            LIMIT 1
            """,
            (job_type, logical_key),
        ).fetchone()
    if row is None:
        return None
    return {
        "job_id": str(row[0]),
        "process_id": str(row[1]),
        "status": str(row[2]),
        "scheduled_at": str(row[3]),
    }
