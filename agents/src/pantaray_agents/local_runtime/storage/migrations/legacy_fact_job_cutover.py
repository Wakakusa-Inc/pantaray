from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime

from pantaray_agents.local_runtime.activity_summary_schedule import iso_z

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")
_CUTOVER_CODE = "LEGACY_FACT_JOB_CUTOVER"


def apply_legacy_fact_job_cutover(
    connection: sqlite3.Connection,
    *,
    cutover_at: datetime | None = None,
) -> None:
    resolved_cutover = (
        datetime.now(UTC) if cutover_at is None else cutover_at.astimezone(UTC)
    )
    cutover_at_iso = iso_z(resolved_cutover)
    for job_id, user_id, process_id, payload_json in _load_active_fact_jobs(connection):
        if _has_source_activity_summary_id(payload_json):
            continue
        _reset_bound_trigger(
            connection=connection,
            job_id=job_id,
            user_id=user_id,
        )
        _cancel_runtime_rows(
            connection=connection,
            job_id=job_id,
            user_id=user_id,
            process_id=process_id,
            cutover_at=cutover_at_iso,
        )


def _load_active_fact_jobs(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str], ...]:
    placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    rows = connection.execute(
        f"""
        SELECT jobs.job_id, jobs.user_id, jobs.process_id, payloads.payload_json
        FROM jobs
        LEFT JOIN job_payloads AS payloads ON payloads.job_id = jobs.job_id
        WHERE jobs.job_type = 'structure_facts'
          AND jobs.status IN ({placeholders})
        ORDER BY jobs.scheduled_at, jobs.job_id
        """,
        _ACTIVE_JOB_STATUSES,
    ).fetchall()
    return tuple(
        (
            str(row[0]),
            str(row[1]),
            str(row[2] or "").strip(),
            str(row[3] or ""),
        )
        for row in rows
    )


def _has_source_activity_summary_id(payload_json: str) -> bool:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError:
        return False
    if not isinstance(payload, dict):
        return False
    source_id = payload.get("source_activity_summary_id")
    return isinstance(source_id, str) and bool(source_id.strip())


def _reset_bound_trigger(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    user_id: str,
) -> None:
    connection.execute(
        """
        UPDATE memory_agent_triggers
        SET status = 'pending', dispatched_job_id = NULL,
            outcome_code = NULL, handled_at = NULL
        WHERE user_id = ?
          AND trigger_kind = 'fact_from_24h_summary'
          AND status = 'dispatched'
          AND dispatched_job_id = ?
        """,
        (user_id, job_id),
    )


def _cancel_runtime_rows(
    *,
    connection: sqlite3.Connection,
    job_id: str,
    user_id: str,
    process_id: str,
    cutover_at: str,
) -> None:
    connection.execute(
        """
        UPDATE job_attempts
        SET status = 'canceled', completed_at = ?, error_code = ?,
            error_message = 'Canceled during legacy Fact job cutover'
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
            WHERE process_id = ? AND user_id = ? AND kind = 'fact'
              AND status IN ({process_placeholders})
            """,
            (
                cutover_at,
                cutover_at,
                cutover_at,
                process_id,
                user_id,
                *_ACTIVE_PROCESS_STATUSES,
            ),
        )
    job_placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    connection.execute(
        f"""
        UPDATE jobs
        SET status = 'canceled', completed_at = ?, error_code = ?,
            claimed_by = NULL, claimed_at = NULL, heartbeat_at = NULL
        WHERE job_id = ? AND user_id = ? AND job_type = 'structure_facts'
          AND status IN ({job_placeholders})
        """,
        (
            cutover_at,
            _CUTOVER_CODE,
            job_id,
            user_id,
            *_ACTIVE_JOB_STATUSES,
        ),
    )


__all__ = ["apply_legacy_fact_job_cutover"]
