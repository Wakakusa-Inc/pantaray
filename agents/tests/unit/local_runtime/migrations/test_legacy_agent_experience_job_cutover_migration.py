from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import load_default_migrations
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .support import _insert_user, _migrations_before, apply_migrations

MIGRATION_NAME = "0100_legacy_agent_experience_job_cutover.sql"
BUSY_TIMEOUT_MS = 1_000
USER_ID = "user-1"
NOW = "2026-09-07T00:00:00Z"


def _seed_inflight_extraction(connection: sqlite3.Connection) -> None:
    _insert_user(connection, USER_ID)
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, started_at, updated_at,
            heartbeat_at, current_job_id, next_event_seq
        ) VALUES ('process-experience', ?, 'agent_experience', 'running', ?, ?, ?,
                  'job-experience', 1)
        """,
        (USER_ID, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO jobs(
            job_id, user_id, job_type, process_id, status, scheduled_at,
            logical_key, claimed_by, claimed_at, heartbeat_at
        ) VALUES ('job-experience', ?, 'extract_agent_experience',
                  'process-experience', 'running', ?, 'job-experience',
                  'worker-1', ?, ?)
        """,
        (USER_ID, NOW, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO job_attempts(
            attempt_id, job_id, attempt_number, status, started_at
        ) VALUES ('attempt-1', 'job-experience', 1, 'running', ?)
        """,
        (NOW,),
    )
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id, user_id, initial_user_message_id, status,
            execution_target_json, final_output, prompt_name, prompt_version,
            created_at, updated_at
        ) VALUES ('action-done', ?, 'message-1', 'success', '{}', 'done',
                  'action/executing', '1.0', ?, ?)
        """,
        (USER_ID, NOW, NOW),
    )
    connection.execute(
        """
        INSERT INTO agent_experience_extraction_runs(
            user_id, job_id, action_id, operation, experience_id,
            superseded_experience_id, revision_id, prompt_name, prompt_version,
            completed_at
        ) VALUES (?, 'job-experience', 'action-done', 'no_change', NULL, NULL,
                  NULL, 'agent_experience/extract', '1.0', ?)
        """,
        (USER_ID, NOW),
    )


def test_cutover_cancels_inflight_extraction_and_keeps_its_history(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.sqlite3"
    apply_migrations(
        db_path,
        BUSY_TIMEOUT_MS,
        _migrations_before(load_default_migrations(), MIGRATION_NAME),
    )
    with closing(sqlite3.connect(db_path)) as connection:
        configure_connection(connection, BUSY_TIMEOUT_MS)
        _seed_inflight_extraction(connection)
        connection.commit()

    apply_migrations(db_path, BUSY_TIMEOUT_MS, load_default_migrations())

    with closing(sqlite3.connect(db_path)) as connection:
        job = connection.execute(
            """
            SELECT status, error_code, claimed_by, claimed_at, heartbeat_at
            FROM jobs WHERE job_id = 'job-experience'
            """
        ).fetchone()
        process = connection.execute(
            """
            SELECT status, current_job_id FROM processes
            WHERE process_id = 'process-experience'
            """
        ).fetchone()
        attempt = connection.execute(
            "SELECT status, error_code FROM job_attempts WHERE attempt_id = 'attempt-1'"
        ).fetchone()
        history = connection.execute(
            """
            SELECT job_id, operation FROM agent_experience_extraction_runs
            WHERE user_id = ?
            """,
            (USER_ID,),
        ).fetchall()

    assert job == (
        "canceled",
        "LEGACY_AGENT_EXPERIENCE_JOB_CUTOVER",
        None,
        None,
        None,
    )
    assert process == ("canceled", None)
    assert attempt == ("canceled", "LEGACY_AGENT_EXPERIENCE_JOB_CUTOVER")
    assert history == [("job-experience", "no_change")]
