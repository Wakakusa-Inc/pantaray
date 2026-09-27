from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _migrations_before, apply_migrations, load_default_migrations

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
MIGRATION_NAME = "0081_legacy_fact_job_cutover.sql"


def _apply_before_cutover(db_path: Path) -> None:
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_before(load_default_migrations(), MIGRATION_NAME),
    )


def _insert_user(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', '2026-08-16T00:00:00Z', '2026-08-16T00:00:00Z')
        """,
        (USER_ID,),
    )


def _insert_fact_job(
    connection: sqlite3.Connection,
    *,
    job_id: str,
    process_id: str,
    job_status: str,
    process_status: str,
    payload_json: str,
) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, started_at, updated_at,
            heartbeat_at, current_job_id, next_event_seq
        ) VALUES (?, ?, 'fact', ?, '2026-08-16T01:00:00Z',
                  '2026-08-16T01:00:00Z', '2026-08-16T01:00:00Z', ?, 1)
        """,
        (process_id, USER_ID, process_status, job_id),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, scheduled_at, logical_key
        ) VALUES (?, ?, 'structure_facts', ?, ?, '2026-08-16T01:00:00Z', ?)
        """,
        (job_id, USER_ID, process_id, job_status, USER_ID),
    )
    connection.execute(
        "INSERT INTO job_payloads(job_id, payload_json) VALUES (?, ?)",
        (job_id, payload_json),
    )


def _legacy_payload(*, job_id: str, process_id: str) -> str:
    return json.dumps(
        {
            "job_id": job_id,
            "process_id": process_id,
            "fact_id": "fact-1",
            "fact_created_at": "2026-08-16T01:00:00Z",
            "user_id": USER_ID,
            "enqueued_at": "2026-08-16T01:00:00Z",
        }
    )


def _current_payload(*, job_id: str, process_id: str) -> str:
    payload = json.loads(_legacy_payload(job_id=job_id, process_id=process_id))
    payload["source_activity_summary_id"] = "summary-current"
    return json.dumps(payload)


def _insert_dispatched_trigger(
    connection: sqlite3.Connection,
    *,
    source_id: str,
    job_id: str,
) -> None:
    connection.execute(
        """
        INSERT INTO memory_agent_triggers(
            user_id, trigger_kind, source_id, status, dispatched_job_id,
            outcome_code, created_at, handled_at
        ) VALUES (?, 'fact_from_24h_summary', ?, 'dispatched', ?,
                  'JOB_ENQUEUED', '2026-08-16T01:00:00Z',
                  '2026-08-16T01:00:00Z')
        """,
        (USER_ID, source_id, job_id),
    )


def _insert_fact_source(connection: sqlite3.Connection, *, summary_id: str) -> None:
    connection.execute(
        """
        INSERT INTO activity_logs(
            log_id, user_id, period_start, period_end, description, status,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES ('activity-1', ?, '2026-08-15T23:00:00Z',
                  '2026-08-16T00:00:00Z', 'Observed activity', 'success',
                  'activity_description', '1.0', '2026-08-16T00:00:00Z',
                  '2026-08-16T00:00:00Z')
        """,
        (USER_ID,),
    )
    connection.execute(
        """
        INSERT INTO activity_summaries(
            summary_id, user_id, summary_type, period_start, period_end, summary,
            status, prompt_name, prompt_version, source_ids, created_at, updated_at
        ) VALUES (?, ?, '24h', '2026-08-15T00:00:00Z',
                  '2026-08-16T00:00:00Z', 'Daily summary', 'success',
                  'activity_summary', '1.0', '[]', '2026-08-16T01:00:00Z',
                  '2026-08-16T01:00:00Z')
        """,
        (summary_id, USER_ID),
    )


def test_cutover_retires_legacy_job_and_requeues_its_bound_trigger(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_cutover(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_fact_source(connection, summary_id="summary-legacy")
            _insert_fact_job(
                connection,
                job_id="job-legacy",
                process_id="process-legacy",
                job_status="queued",
                process_status="enqueued",
                payload_json=_legacy_payload(
                    job_id="job-legacy", process_id="process-legacy"
                ),
            )
            _insert_dispatched_trigger(
                connection, source_id="summary-legacy", job_id="job-legacy"
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        job = connection.execute(
            "SELECT status, error_code FROM jobs WHERE job_id = 'job-legacy'"
        ).fetchone()
        process = connection.execute(
            "SELECT status, current_job_id FROM processes WHERE process_id = 'process-legacy'"
        ).fetchone()
        trigger = connection.execute(
            """
            SELECT status, dispatched_job_id, outcome_code, handled_at
            FROM memory_agent_triggers
            WHERE user_id = ? AND source_id = 'summary-legacy'
            """,
            (USER_ID,),
        ).fetchone()

    assert job == ("canceled", "LEGACY_FACT_JOB_CUTOVER")
    assert process == ("canceled", None)
    assert trigger == ("pending", None, None, None)


def test_cutover_discards_unbound_corrupt_job_without_blocking_migration(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_cutover(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_fact_job(
                connection,
                job_id="job-corrupt",
                process_id="process-corrupt",
                job_status="running",
                process_status="running",
                payload_json="[]",
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id, job_id, attempt_number, started_at, status
                ) VALUES ('attempt-corrupt', 'job-corrupt', 1,
                          '2026-08-16T01:00:00Z', 'running')
                """
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        job = connection.execute(
            "SELECT status, error_code FROM jobs WHERE job_id = 'job-corrupt'"
        ).fetchone()
        process = connection.execute(
            "SELECT status FROM processes WHERE process_id = 'process-corrupt'"
        ).fetchone()
        attempt = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE attempt_id = 'attempt-corrupt'"
        ).fetchone()

    assert job == ("canceled", "LEGACY_FACT_JOB_CUTOVER")
    assert process == ("canceled",)
    assert attempt == ("canceled", "LEGACY_FACT_JOB_CUTOVER")


def test_cutover_leaves_current_and_completed_jobs_unchanged(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_before_cutover(db_path)
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            _insert_fact_job(
                connection,
                job_id="job-current",
                process_id="process-current",
                job_status="queued",
                process_status="enqueued",
                payload_json=_current_payload(
                    job_id="job-current", process_id="process-current"
                ),
            )
            _insert_dispatched_trigger(
                connection, source_id="summary-current", job_id="job-current"
            )
            _insert_fact_job(
                connection,
                job_id="job-completed",
                process_id="process-completed",
                job_status="completed",
                process_status="completed",
                payload_json=_legacy_payload(
                    job_id="job-completed", process_id="process-completed"
                ),
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        jobs = connection.execute(
            """
            SELECT job_id, status, error_code
            FROM jobs
            WHERE job_id IN ('job-current', 'job-completed')
            ORDER BY job_id
            """
        ).fetchall()
        trigger = connection.execute(
            """
            SELECT status, dispatched_job_id
            FROM memory_agent_triggers
            WHERE user_id = ? AND source_id = 'summary-current'
            """,
            (USER_ID,),
        ).fetchone()

    assert jobs == [
        ("job-completed", "completed", None),
        ("job-current", "queued", None),
    ]
    assert trigger == ("dispatched", "job-current")
