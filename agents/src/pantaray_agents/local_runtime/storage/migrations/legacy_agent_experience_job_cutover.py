"""Terminate the retired per-Action Agent Experience runtime.

The unified Memory run replaced ``extract_agent_experience``: no producer
enqueues it and no worker spec can execute it, so an active job or process left
from an earlier build would hold its Action's resources forever. Their durable
results — published entries and ``agent_experience_extraction_runs`` rows —
stay as history.
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime

from pantaray_agents.local_runtime.activity_summary_schedule import iso_z

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")
_CUTOVER_CODE = "LEGACY_AGENT_EXPERIENCE_JOB_CUTOVER"


def apply_legacy_agent_experience_job_cutover(
    connection: sqlite3.Connection,
    *,
    cutover_at: datetime | None = None,
) -> None:
    resolved = datetime.now(UTC) if cutover_at is None else cutover_at.astimezone(UTC)
    cutover_at_iso = iso_z(resolved)
    job_placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    process_placeholders = ",".join("?" for _ in _ACTIVE_PROCESS_STATUSES)
    connection.execute(
        f"""
        UPDATE job_attempts
        SET status = 'canceled', completed_at = ?, error_code = ?,
            error_message = 'Canceled during Agent Experience job cutover'
        WHERE status = 'running' AND job_id IN (
            SELECT job_id FROM jobs
            WHERE job_type = 'extract_agent_experience'
              AND status IN ({job_placeholders})
        )
        """,
        (cutover_at_iso, _CUTOVER_CODE, *_ACTIVE_JOB_STATUSES),
    )
    connection.execute(
        f"""
        UPDATE processes
        SET status = 'canceled', completed_at = ?, updated_at = ?,
            heartbeat_at = ?, current_job_id = NULL
        WHERE kind = 'agent_experience'
          AND status IN ({process_placeholders})
        """,
        (
            cutover_at_iso,
            cutover_at_iso,
            cutover_at_iso,
            *_ACTIVE_PROCESS_STATUSES,
        ),
    )
    connection.execute(
        f"""
        UPDATE jobs
        SET status = 'canceled', completed_at = ?, error_code = ?,
            claimed_by = NULL, claimed_at = NULL, heartbeat_at = NULL
        WHERE job_type = 'extract_agent_experience'
          AND status IN ({job_placeholders})
        """,
        (cutover_at_iso, _CUTOVER_CODE, *_ACTIVE_JOB_STATUSES),
    )


__all__ = ["apply_legacy_agent_experience_job_cutover"]
