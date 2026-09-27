"""Terminate the retired FactStructuring and InsightUpdate runtime.

The unified ``memory_update`` run replaced ``structure_facts`` and
``update_insight``: nothing enqueues them and no worker spec can execute them,
so an active job or process left by an earlier build would hold its worker slot
forever, and a pending trigger of a retired kind would never be handled.

``memory_agent_triggers.trigger_kind`` keeps the two retired names in its CHECK
constraint. Narrowing it would mean rebuilding the table, and the copy would
reject every dispatched, skipped, or blocked row of a retired kind — the audit
trail this cutover is closing. The producing Literal is the current contract;
migrations are forward-only, so no build that still writes those kinds can run
against this schema.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pantaray_agents.local_runtime.activity_summary_schedule import iso_z

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")
_RETIRED_JOB_TYPES = ("structure_facts", "update_insight")
_RETIRED_TRIGGER_KINDS = ("fact_from_24h_summary", "insight_update_from_insight")
_CUTOVER_CODE = "LEGACY_MEMORY_AGENT_CUTOVER"


def apply_legacy_memory_agent_cutover(
    connection: sqlite3.Connection,
    *,
    cutover_at: datetime | None = None,
) -> None:
    resolved = datetime.now(UTC) if cutover_at is None else cutover_at.astimezone(UTC)
    cutover_at_iso = iso_z(resolved)
    _skip_pending_retired_triggers(connection=connection, cutover_at=cutover_at_iso)
    for job_id, process_id in _load_active_retired_jobs(connection):
        _cancel_runtime_rows(
            connection=connection,
            job_id=job_id,
            process_id=process_id,
            cutover_at=cutover_at_iso,
        )


def _skip_pending_retired_triggers(
    *, connection: sqlite3.Connection, cutover_at: str
) -> None:
    placeholders = ",".join("?" for _ in _RETIRED_TRIGGER_KINDS)
    connection.execute(
        f"""
        UPDATE memory_agent_triggers
        SET status = 'skipped', outcome_code = ?, handled_at = ?
        WHERE status = 'pending' AND trigger_kind IN ({placeholders})
        """,
        (_CUTOVER_CODE, cutover_at, *_RETIRED_TRIGGER_KINDS),
    )


def _load_active_retired_jobs(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str], ...]:
    type_placeholders = ",".join("?" for _ in _RETIRED_JOB_TYPES)
    status_placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    rows = connection.execute(
        f"""
        SELECT job_id, process_id
        FROM jobs
        WHERE job_type IN ({type_placeholders})
          AND status IN ({status_placeholders})
        ORDER BY scheduled_at, job_id
        """,
        (*_RETIRED_JOB_TYPES, *_ACTIVE_JOB_STATUSES),
    ).fetchall()
    return tuple((str(row[0]), str(row[1] or "").strip()) for row in rows)


def _cancel_runtime_rows(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    process_id: str,
    cutover_at: str,
) -> None:
    connection.execute(
        """
        UPDATE job_attempts
        SET status = 'canceled', completed_at = ?, error_code = ?,
            error_message = 'Canceled during legacy Memory agent cutover'
        WHERE job_id = ? AND status = 'running'
        """,
        (cutover_at, _CUTOVER_CODE, job_id),
    )
    if process_id:
        process_placeholders = ",".join("?" for _ in _ACTIVE_PROCESS_STATUSES)
        connection.execute(
            f"""
            UPDATE processes
            SET status = 'canceled', completed_at = ?, updated_at = ?,
                heartbeat_at = ?, current_job_id = NULL
            WHERE process_id = ? AND status IN ({process_placeholders})
            """,
            (
                cutover_at,
                cutover_at,
                cutover_at,
                process_id,
                *_ACTIVE_PROCESS_STATUSES,
            ),
        )
    job_placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    connection.execute(
        f"""
        UPDATE jobs
        SET status = 'canceled', completed_at = ?, error_code = ?,
            claimed_by = NULL, claimed_at = NULL, heartbeat_at = NULL
        WHERE job_id = ? AND status IN ({job_placeholders})
        """,
        (cutover_at, _CUTOVER_CODE, job_id, *_ACTIVE_JOB_STATUSES),
    )


__all__ = ["apply_legacy_memory_agent_cutover"]
