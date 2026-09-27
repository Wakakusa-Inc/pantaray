from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.activity_queue import (
    build_local_activity_summary_enqueue_request,
)
from pantaray_agents.local_runtime.runtime.job_enqueue import enqueue_local_job
from pantaray_agents.local_runtime.runtime.job_payload_builder import (
    build_activity_summary_job_payload,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    apply_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import load_default_migrations

BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"


def _apply_through_79(db_path: Path) -> None:
    migrations = tuple(
        migration for migration in load_default_migrations() if migration.version <= 79
    )
    apply_migrations(db_path, BUSY_TIMEOUT_MS, migrations)


def _insert_user(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        INSERT INTO users(user_id, ui_language, created_at, updated_at)
        VALUES (?, 'ja', '2026-08-16T00:00:00Z', '2026-08-16T00:00:00Z')
        """,
        (USER_ID,),
    )


def test_migration_cuts_over_inflight_summary_state_without_backfill(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_through_79(db_path)
    payload = build_activity_summary_job_payload(
        {
            "job_id": "job-summary",
            "process_id": "process-summary",
            "summary_id": "summary-processing",
            "user_id": USER_ID,
            "enqueued_at": "2026-08-16T01:00:00Z",
            "summary_type": "1h",
            "period_start": "2026-08-16T00:00:00Z",
            "period_end": "2026-08-16T01:00:00Z",
        }
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            connection.execute(
                """
                INSERT INTO activity_summaries(
                    summary_id, user_id, summary_type, period_start, period_end,
                    summary, status, prompt_name, prompt_version, source_ids,
                    created_at, updated_at
                ) VALUES (?, ?, '1h', ?, ?, '', 'processing',
                          'activity_summary', '1.0', '[]', ?, ?)
                """,
                (
                    payload["summary_id"],
                    USER_ID,
                    payload["period_start"],
                    payload["period_end"],
                    payload["enqueued_at"],
                    payload["enqueued_at"],
                ),
            )
            enqueue_local_job(
                connection=connection,
                request=build_local_activity_summary_enqueue_request(payload),
            )
            connection.execute(
                "UPDATE jobs SET status = 'running', attempt = 1 WHERE job_id = ?",
                (payload["job_id"],),
            )
            connection.execute(
                "UPDATE processes SET status = 'running' WHERE process_id = ?",
                (payload["process_id"],),
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id, job_id, attempt_number, started_at, status
                ) VALUES ('attempt-summary', ?, 1, ?, 'running')
                """,
                (payload["job_id"], payload["enqueued_at"]),
            )
            connection.execute(
                """
                INSERT INTO scheduler_jobs(job_name, job_kind, status)
                VALUES ('activity_summary_1h', 'activity_summary', 'active')
                """
            )
            connection.execute(
                """
                INSERT INTO scheduler_job_runs(
                    run_id, job_name, logical_window_start, logical_window_end,
                    status, attempt, enqueued_at, started_at
                ) VALUES ('scheduler-run', 'activity_summary_1h', ?, ?,
                          'running', 1, ?, ?)
                """,
                (
                    payload["period_start"],
                    payload["period_end"],
                    payload["enqueued_at"],
                    payload["enqueued_at"],
                ),
            )
            connection.execute(
                """
                INSERT INTO activity_summaries(
                    summary_id, user_id, summary_type, period_start, period_end,
                    summary, status, prompt_name, prompt_version, source_ids,
                    created_at, updated_at
                ) VALUES ('summary-old', ?, '1h', ?, ?, 'old', 'success',
                          'activity_summary', '1.0', '["log-old"]', ?, ?)
                """,
                (
                    USER_ID,
                    "2026-08-15T23:00:00Z",
                    "2026-08-16T00:00:00Z",
                    "2026-08-16T00:00:00Z",
                    "2026-08-16T00:00:00Z",
                ),
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        summary_status = connection.execute(
            "SELECT status FROM activity_summaries WHERE summary_id = ?",
            (payload["summary_id"],),
        ).fetchone()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (payload["job_id"],)
        ).fetchone()
        process_status = connection.execute(
            "SELECT status FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
        attempt_status = connection.execute(
            "SELECT status FROM job_attempts WHERE attempt_id = 'attempt-summary'"
        ).fetchone()
        scheduler_run = connection.execute(
            "SELECT status, error_code FROM scheduler_job_runs WHERE run_id = 'scheduler-run'"
        ).fetchone()
        scheduler_job = connection.execute(
            """
            SELECT cursor_value, next_run_after
            FROM scheduler_jobs WHERE job_name = 'activity_summary_1h'
            """
        ).fetchone()
        trigger_count = connection.execute(
            "SELECT COUNT(*) FROM memory_agent_triggers"
        ).fetchone()

    assert summary_status == ("canceled",)
    assert job_status == ("canceled",)
    assert process_status == ("canceled",)
    assert attempt_status == ("canceled",)
    assert scheduler_run == ("skipped", "MEMORY_AGENT_TRIGGER_CUTOVER")
    assert scheduler_job is not None
    assert all(value is not None for value in scheduler_job)
    assert trigger_count == (0,)


def test_migration_cancels_queued_summary_without_requiring_running_attempt(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_through_79(db_path)
    payload = build_activity_summary_job_payload(
        {
            "job_id": "job-summary-queued",
            "process_id": "process-summary-queued",
            "summary_id": "summary-queued",
            "user_id": USER_ID,
            "enqueued_at": "2026-08-16T01:00:00Z",
            "summary_type": "1h",
            "period_start": "2026-08-16T00:00:00Z",
            "period_end": "2026-08-16T01:00:00Z",
        }
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            connection.execute(
                """
                INSERT INTO activity_summaries(
                    summary_id, user_id, summary_type, period_start, period_end,
                    summary, status, prompt_name, prompt_version, source_ids,
                    created_at, updated_at
                ) VALUES (?, ?, '1h', ?, ?, '', 'processing',
                          'activity_summary', '1.0', '[]', ?, ?)
                """,
                (
                    payload["summary_id"],
                    USER_ID,
                    payload["period_start"],
                    payload["period_end"],
                    payload["enqueued_at"],
                    payload["enqueued_at"],
                ),
            )
            enqueue_local_job(
                connection=connection,
                request=build_local_activity_summary_enqueue_request(payload),
            )

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        summary_status = connection.execute(
            "SELECT status FROM activity_summaries WHERE summary_id = ?",
            (payload["summary_id"],),
        ).fetchone()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = ?", (payload["job_id"],)
        ).fetchone()
        process_status = connection.execute(
            "SELECT status FROM processes WHERE process_id = ?",
            (payload["process_id"],),
        ).fetchone()
        attempt_count = connection.execute(
            "SELECT COUNT(*) FROM job_attempts WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()

    assert summary_status == ("canceled",)
    assert job_status == ("canceled",)
    assert process_status == ("canceled",)
    assert attempt_count == (0,)


def test_migration_rejects_active_job_without_active_owned_process(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_through_79(db_path)
    payload = build_activity_summary_job_payload(
        {
            "job_id": "job-summary",
            "process_id": "process-summary",
            "summary_id": "summary-processing",
            "user_id": USER_ID,
            "enqueued_at": "2026-08-16T01:00:00Z",
            "summary_type": "1h",
            "period_start": "2026-08-16T00:00:00Z",
            "period_end": "2026-08-16T01:00:00Z",
        }
    )
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        with connection:
            _insert_user(connection)
            connection.execute(
                """
                INSERT INTO activity_summaries(
                    summary_id, user_id, summary_type, period_start, period_end,
                    summary, status, prompt_name, prompt_version, source_ids,
                    created_at, updated_at
                ) VALUES (?, ?, '1h', ?, ?, '', 'processing',
                          'activity_summary', '1.0', '[]', ?, ?)
                """,
                (
                    payload["summary_id"],
                    USER_ID,
                    payload["period_start"],
                    payload["period_end"],
                    payload["enqueued_at"],
                    payload["enqueued_at"],
                ),
            )
            enqueue_local_job(
                connection=connection,
                request=build_local_activity_summary_enqueue_request(payload),
            )
            connection.execute(
                "UPDATE jobs SET status = 'running', attempt = 1 WHERE job_id = ?",
                (payload["job_id"],),
            )
            connection.execute(
                "UPDATE processes SET status = 'completed' WHERE process_id = ?",
                (payload["process_id"],),
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id, job_id, attempt_number, started_at, status
                ) VALUES ('attempt-summary', ?, 1, ?, 'running')
                """,
                (payload["job_id"], payload["enqueued_at"]),
            )

    with pytest.raises(
        MigrationError, match="active Activity Summary job has no active owned process"
    ):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()
        summary_status = connection.execute(
            "SELECT status FROM activity_summaries WHERE summary_id = ?",
            (payload["summary_id"],),
        ).fetchone()
        attempt_status = connection.execute(
            "SELECT status FROM job_attempts WHERE job_id = ?",
            (payload["job_id"],),
        ).fetchone()

    assert version == (79,)
    assert summary_status == ("processing",)
    assert attempt_status == ("running",)


def test_migration_rolls_back_schema_and_cutover_together(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    _apply_through_79(db_path)
    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection)
            connection.execute(
                """
                INSERT INTO scheduler_jobs(job_name, job_kind, status)
                VALUES ('unknown_summary', 'activity_summary', 'active')
                """
            )

    with pytest.raises(MigrationError, match="unknown Activity Summary scheduler"):
        apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()
        trigger_table = connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'memory_agent_triggers'
            """
        ).fetchone()
        scheduler = connection.execute(
            "SELECT job_kind FROM scheduler_jobs WHERE job_name = 'unknown_summary'"
        ).fetchone()

    assert version == (79,)
    assert trigger_table is None
    assert scheduler == ("activity_summary",)
