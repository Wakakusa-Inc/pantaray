from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.activity_summary_schedule import SummaryType
from pantaray_agents.tasks.types import ActivitySummaryJobPayload

from ..storage.migrations import MigrationError
from ..storage.migrations.connection import configure_connection
from ..storage.transactions import immediate_transaction
from .job_enqueue import (
    LocalJobEnqueueRequest,
    LocalJobEnqueueResult,
    enqueue_local_job,
)
from .job_payload_models import parse_activity_summary_job_payload_json
from .job_status import FINALIZABLE_JOB_STATUSES, PROCESS_STATUS_ENQUEUED
from .job_types import (
    ACTIVITY_SUMMARY_PROCESS_KIND,
    LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
)
from .process_events import append_process_event_in_connection


def enqueue_local_activity_summary_job(
    *,
    payload: ActivitySummaryJobPayload,
    db_path: Path,
    busy_timeout_ms: int,
) -> LocalJobEnqueueResult:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            return enqueue_local_activity_summary_job_in_connection(
                connection=connection,
                payload=payload,
            )


def enqueue_local_activity_summary_job_in_connection(
    *,
    connection: sqlite3.Connection,
    payload: ActivitySummaryJobPayload,
) -> LocalJobEnqueueResult:
    result = enqueue_local_job(
        connection=connection,
        request=build_local_activity_summary_enqueue_request(payload),
    )
    if result["inserted_new"]:
        append_process_event_in_connection(
            connection=connection,
            process_id=payload["process_id"],
            event_name="activity_summary_requested",
            payload={
                "process_id": payload["process_id"],
                "summary_id": payload["summary_id"],
                "summary_type": payload["summary_type"],
                "period_start": payload["period_start"],
                "period_end": payload["period_end"],
                "enqueued_at": payload["enqueued_at"],
            },
            created_at=payload["enqueued_at"],
        )
    return result


def build_local_activity_summary_enqueue_request(
    payload: ActivitySummaryJobPayload,
) -> LocalJobEnqueueRequest:
    return {
        "job_id": payload["job_id"],
        "user_id": payload["user_id"],
        "job_type": LOCAL_ACTIVITY_SUMMARY_JOB_TYPE,
        "process_id": payload["process_id"],
        "process_kind": ACTIVITY_SUMMARY_PROCESS_KIND,
        "process_status": PROCESS_STATUS_ENQUEUED,
        "scheduled_at": payload["enqueued_at"],
        "logical_key": payload["summary_id"],
        "payload_json": json.dumps(payload, ensure_ascii=False),
        "process_started_at": payload["enqueued_at"],
        "process_updated_at": payload["enqueued_at"],
        "process_heartbeat_at": payload["enqueued_at"],
        "process_next_event_seq": 1,
    }


def has_unfinished_activity_summary_job(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    summary_types: tuple[SummaryType, ...],
    window_start: str,
    window_end: str,
) -> bool:
    """Report whether a shorter period in the window still owes a summary row.

    Every summary above 1h reads the `activity_summaries` rows of the shorter
    types. Summarizing the window while one of those periods is still queued
    silently drops it, and the run that follows advances the cursor past the
    window for good.
    """
    if not summary_types:
        return False
    rows = connection.execute(
        f"""SELECT job_payloads.payload_json
            FROM jobs JOIN job_payloads ON job_payloads.job_id = jobs.job_id
            WHERE jobs.user_id = ? AND jobs.job_type = ?
              AND jobs.status NOT IN
                  ({",".join("?" for _ in FINALIZABLE_JOB_STATUSES)})""",
        (user_id, LOCAL_ACTIVITY_SUMMARY_JOB_TYPE, *FINALIZABLE_JOB_STATUSES),
    ).fetchall()
    return any(
        payload["summary_type"] in summary_types
        and window_start <= payload["period_start"]
        and payload["period_end"] <= window_end
        for payload in (
            parse_activity_summary_job_payload_json(str(row[0])) for row in rows
        )
    )
