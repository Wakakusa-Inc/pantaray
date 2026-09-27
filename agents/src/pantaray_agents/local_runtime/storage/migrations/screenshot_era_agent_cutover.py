"""Terminate the retired ActivityDescription and SuggestionCritic runtime.

Zanei recording replaced automatic screenshot collection and the short
Insight run became the writer of ``activity_logs``, so nothing enqueues
``describe_activity`` or ``evaluate_suggestion_critic`` and no worker spec can
execute them. A job of either kind left active by an earlier build would never
be claimed, and its process would stay enqueued or running forever.

``processes.kind`` keeps ``activity_description`` and ``suggestion_critic`` in
its CHECK constraint: narrowing it would mean rebuilding the table, and the
copy would reject the very rows this cutover terminates. ``activity_logs`` and
``agent_suggestion_critics`` rows are history and stay as they are; every
reader of ``activity_logs`` already selects only successful rows.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pantaray_agents.local_runtime.activity_summary_schedule import iso_z

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")
_RETIRED_JOB_TYPES = ("describe_activity", "evaluate_suggestion_critic")
_CUTOVER_CODE = "SCREENSHOT_ERA_AGENT_CUTOVER"


def apply_screenshot_era_agent_cutover(
    connection: sqlite3.Connection,
    *,
    cutover_at: datetime | None = None,
) -> None:
    resolved = datetime.now(UTC) if cutover_at is None else cutover_at.astimezone(UTC)
    cutover_at_iso = iso_z(resolved)
    for job_id, process_id in _load_active_retired_jobs(connection):
        _cancel_runtime_rows(
            connection=connection,
            job_id=job_id,
            process_id=process_id,
            cutover_at=cutover_at_iso,
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
            error_message = 'Canceled during screenshot-era agent cutover'
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


__all__ = ["apply_screenshot_era_agent_cutover"]
