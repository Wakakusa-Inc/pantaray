from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta

from pantaray_agents.local_runtime.activity_summary_schedule import (
    ACTIVITY_SUMMARY_SCHEDULE_SPECS,
    iso_z,
    latest_eligible_window,
    next_period_end,
)

from .specs import MigrationError
from .sql_script import execute_sql_statements

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")
_CUTOVER_CODE = "MEMORY_AGENT_TRIGGER_CUTOVER"


def apply_memory_agent_trigger_migration(
    connection: sqlite3.Connection,
    *,
    migration_statements: tuple[str, ...],
    cutover_at: datetime | None = None,
) -> None:
    execute_sql_statements(connection, migration_statements)
    resolved_cutover = (
        datetime.now(UTC) if cutover_at is None else cutover_at.astimezone(UTC)
    )
    cutover_at_iso = iso_z(resolved_cutover)
    summary_jobs = _load_active_summary_jobs(connection)
    _cancel_active_summary_sources(
        connection=connection,
        summary_jobs=summary_jobs,
        cutover_at=cutover_at_iso,
    )
    _cancel_active_summary_runtime_rows(
        connection=connection,
        summary_jobs=summary_jobs,
        cutover_at=cutover_at_iso,
    )
    _close_running_scheduler_runs(connection=connection, cutover_at=cutover_at_iso)
    _rebase_activity_summary_schedulers(
        connection=connection,
        cutover_at=resolved_cutover,
    )


def _load_active_summary_jobs(
    connection: sqlite3.Connection,
) -> tuple[tuple[str, str, str, str], ...]:
    placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
    rows = connection.execute(
        f"""
        SELECT jobs.job_id, jobs.user_id, jobs.process_id, payloads.payload_json,
               processes.user_id, processes.kind
        FROM jobs
        LEFT JOIN job_payloads AS payloads ON payloads.job_id = jobs.job_id
        LEFT JOIN processes ON processes.process_id = jobs.process_id
        WHERE jobs.job_type = 'summarize_activity'
          AND jobs.status IN ({placeholders})
        ORDER BY jobs.scheduled_at, jobs.job_id
        """,
        _ACTIVE_JOB_STATUSES,
    ).fetchall()
    validated: list[tuple[str, str, str, str]] = []
    for row in rows:
        job_id = str(row[0])
        user_id = str(row[1])
        process_id = str(row[2] or "").strip()
        payload_json = str(row[3] or "").strip()
        process_user_id = str(row[4] or "").strip()
        process_kind = str(row[5] or "").strip()
        if not process_id or not payload_json:
            raise MigrationError("active Activity Summary job envelope is incomplete")
        if process_user_id != user_id or process_kind != "activity_summary":
            raise MigrationError(
                "active Activity Summary process identity is inconsistent"
            )
        try:
            payload = json.loads(payload_json)
        except json.JSONDecodeError as exc:
            raise MigrationError("active Activity Summary payload is invalid") from exc
        if not isinstance(payload, dict):
            raise MigrationError("active Activity Summary payload must be an object")
        summary_id = payload.get("summary_id")
        if (
            not isinstance(summary_id, str)
            or not summary_id.strip()
            or payload.get("job_id") != job_id
            or payload.get("process_id") != process_id
            or payload.get("user_id") != user_id
        ):
            raise MigrationError("active Activity Summary identity is inconsistent")
        validated.append((job_id, process_id, user_id, summary_id))
    return tuple(validated)


def _cancel_active_summary_sources(
    *,
    connection: sqlite3.Connection,
    summary_jobs: tuple[tuple[str, str, str, str], ...],
    cutover_at: str,
) -> None:
    for _job_id, _process_id, user_id, summary_id in summary_jobs:
        cursor = connection.execute(
            """
            UPDATE activity_summaries
            SET status = 'canceled', updated_at = ?
            WHERE summary_id = ? AND user_id = ? AND status = 'processing'
            """,
            (cutover_at, summary_id, user_id),
        )
        if cursor.rowcount != 1:
            raise MigrationError(
                "active Activity Summary job has no owned processing source"
            )


def _cancel_active_summary_runtime_rows(
    *,
    connection: sqlite3.Connection,
    summary_jobs: tuple[tuple[str, str, str, str], ...],
    cutover_at: str,
) -> None:
    for job_id, process_id, _user_id, _summary_id in summary_jobs:
        attempt_cursor = connection.execute(
            """
            UPDATE job_attempts
            SET status = 'canceled', completed_at = ?, error_code = ?,
                error_message = 'Canceled during Memory Agent trigger cutover'
            WHERE job_id = ? AND status = 'running'
            """,
            (cutover_at, _CUTOVER_CODE, job_id),
        )
        if attempt_cursor.rowcount > 1:
            raise MigrationError(
                "active Activity Summary job has multiple running attempts"
            )
        process_placeholders = ",".join("?" for _ in _ACTIVE_PROCESS_STATUSES)
        process_cursor = connection.execute(
            f"""
            UPDATE processes
            SET status = 'canceled', completed_at = ?, updated_at = ?, heartbeat_at = ?,
                current_job_id = NULL
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
        if process_cursor.rowcount != 1:
            raise MigrationError(
                "active Activity Summary job has no active owned process"
            )
        job_placeholders = ",".join("?" for _ in _ACTIVE_JOB_STATUSES)
        job_cursor = connection.execute(
            f"""
            UPDATE jobs
            SET status = 'canceled', completed_at = ?, error_code = ?,
                claimed_by = NULL, claimed_at = NULL, heartbeat_at = NULL
            WHERE job_id = ? AND status IN ({job_placeholders})
            """,
            (cutover_at, _CUTOVER_CODE, job_id, *_ACTIVE_JOB_STATUSES),
        )
        if job_cursor.rowcount != 1:
            raise MigrationError(
                "active Activity Summary job disappeared during cutover"
            )


def _close_running_scheduler_runs(
    *, connection: sqlite3.Connection, cutover_at: str
) -> None:
    connection.execute(
        """
        UPDATE scheduler_job_runs
        SET status = 'skipped', error_code = ?,
            error_details_json = ?, completed_at = ?
        WHERE status = 'running'
          AND job_name IN (
              SELECT job_name FROM scheduler_jobs WHERE job_kind = 'activity_summary'
          )
        """,
        (
            _CUTOVER_CODE,
            json.dumps(
                {"reason": "superseded by Memory Agent trigger cutover"},
                ensure_ascii=False,
            ),
            cutover_at,
        ),
    )


def _rebase_activity_summary_schedulers(
    *,
    connection: sqlite3.Connection,
    cutover_at: datetime,
) -> None:
    specs_by_name = {spec.job_name: spec for spec in ACTIVITY_SUMMARY_SCHEDULE_SPECS}
    rows = connection.execute(
        """
        SELECT job_name
        FROM scheduler_jobs
        WHERE job_kind = 'activity_summary'
        ORDER BY job_name
        """
    ).fetchall()
    for row in rows:
        job_name = str(row[0])
        spec = specs_by_name.get(job_name)
        if spec is None:
            raise MigrationError(f"unknown Activity Summary scheduler: {job_name}")
        window = latest_eligible_window(spec=spec, now=cutover_at)
        next_run_after = next_period_end(
            window.period_end, spec.summary_type
        ) + timedelta(seconds=spec.grace_seconds)
        connection.execute(
            """
            UPDATE scheduler_jobs
            SET cursor_value = ?, next_run_after = ?
            WHERE job_name = ?
            """,
            (
                iso_z(window.period_start),
                iso_z(next_run_after),
                job_name,
            ),
        )


__all__ = ["apply_memory_agent_trigger_migration"]
