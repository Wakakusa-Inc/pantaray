from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import load_default_migrations
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, _migrations_before, apply_migrations

MIGRATION_NAME = "0102_screenshot_era_agent_cutover.sql"
BUSY_TIMEOUT_MS = 1_000
CUTOVER_CODE = "SCREENSHOT_ERA_AGENT_CUTOVER"
USER_ID = "user-1"
NOW = "2026-09-07T00:00:00Z"


def _seed_retired_runtime(connection: sqlite3.Connection) -> None:
    _insert_user(connection, USER_ID)
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, started_at, updated_at,
            heartbeat_at, current_job_id, next_event_seq
        ) VALUES
            ('process-describe', ?, 'activity_description', 'running', ?, ?, ?,
             'job-describe', 1),
            ('process-critic', ?, 'suggestion_critic', 'enqueued', ?, ?, ?,
             'job-critic', 1),
            ('process-summary', ?, 'activity_summary', 'running', ?, ?, ?,
             'job-summary', 1)
        """,
        (USER_ID, NOW, NOW, NOW, USER_ID, NOW, NOW, NOW, USER_ID, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, scheduled_at,
            logical_key, claimed_by, claimed_at, heartbeat_at
        ) VALUES
            ('job-describe', ?, 'describe_activity', 'process-describe', 'running',
             ?, 'log-1', 'worker-1', ?, ?),
            ('job-critic', ?, 'evaluate_suggestion_critic', 'process-critic',
             'queued', ?, 'log-1', NULL, NULL, NULL),
            ('job-summary', ?, 'summarize_activity', 'process-summary', 'running',
             ?, 'summary-1', 'worker-1', ?, ?)
        """,
        (USER_ID, NOW, NOW, NOW, USER_ID, NOW, USER_ID, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id, job_id, attempt_number, status, started_at
        ) VALUES
            ('attempt-describe', 'job-describe', 1, 'running', ?),
            ('attempt-summary', 'job-summary', 1, 'running', ?)
        """,
        (NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO activity_logs(
            log_id, user_id, period_start, period_end, description, status,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES ('log-1', ?, ?, ?, 'stored activity', 'success',
                  'activity_description', '1.0', ?, ?)
        """,
        (USER_ID, NOW, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO agent_suggestion_critics(
            critic_id, user_id, decision, status, model, latency_ms,
            critic_input, created_at, updated_at
        ) VALUES ('critic-1', ?, 'triggered', 'success', 'm', 1, '{}', ?, ?)
        """,
        (USER_ID, NOW, NOW),
    )


def _apply_cutover(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.sqlite3"
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_before(load_default_migrations(), MIGRATION_NAME),
    )
    with closing(sqlite3.connect(db_path)) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        _seed_retired_runtime(connection)
        connection.commit()

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())
    return db_path


def test_cutover_cancels_retired_jobs_and_leaves_the_summary_run_alone(
    tmp_path: Path,
) -> None:
    db_path = _apply_cutover(tmp_path)

    with closing(sqlite3.connect(db_path)) as connection:
        jobs = connection.execute(
            """
            SELECT job_id, status, error_code, claimed_by, claimed_at, heartbeat_at
            FROM jobs ORDER BY job_id
            """
        ).fetchall()
        processes = connection.execute(
            "SELECT process_id, status, current_job_id FROM processes ORDER BY process_id"
        ).fetchall()
        attempts = connection.execute(
            "SELECT attempt_id, status, error_code FROM job_attempts ORDER BY attempt_id"
        ).fetchall()
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []

    assert jobs == [
        ("job-critic", "canceled", CUTOVER_CODE, None, None, None),
        ("job-describe", "canceled", CUTOVER_CODE, None, None, None),
        ("job-summary", "running", None, "worker-1", NOW, NOW),
    ]
    assert processes == [
        ("process-critic", "canceled", None),
        ("process-describe", "canceled", None),
        ("process-summary", "running", "job-summary"),
    ]
    assert attempts == [
        ("attempt-describe", "canceled", CUTOVER_CODE),
        ("attempt-summary", "running", None),
    ]


def test_cutover_keeps_the_stored_activity_log_and_critic_history(
    tmp_path: Path,
) -> None:
    db_path = _apply_cutover(tmp_path)

    with closing(sqlite3.connect(db_path)) as connection:
        activity_log = connection.execute(
            "SELECT description, status, prompt_name FROM activity_logs"
        ).fetchall()
        critics = connection.execute(
            "SELECT critic_id, decision, status FROM agent_suggestion_critics"
        ).fetchall()
        process_kinds = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'processes'"
        ).fetchone()

    assert activity_log == [("stored activity", "success", "activity_description")]
    assert critics == [("critic-1", "triggered", "success")]
    assert "'activity_description'" in str(process_kinds[0])
    assert "'suggestion_critic'" in str(process_kinds[0])
