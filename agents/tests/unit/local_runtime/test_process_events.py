from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.process_events import (
    append_local_action_step_event,
    append_local_process_event,
    mark_local_action_job_paused,
    mark_local_action_job_started,
    read_local_process_events_after,
    resolve_local_process_event_cursor,
)
from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    load_default_migrations,
)

from .migrated_db import prepare_test_database


def test_local_process_started_event_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    # minimal process/job bootstrap
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES ('user-1', 'ja', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,
                    user_id,
                    kind,
                    status,
                    started_at,
                    updated_at,
                    heartbeat_at,
                    next_event_seq
                ) VALUES ('process-1', 'user-1', 'action', 'enqueued', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z', 1)
                """
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,
                    user_id,
                    job_type,
                    process_id,
                    status,
                    scheduled_at
                ) VALUES ('job-1', 'user-1', 'execute_action', 'process-1', 'queued', '2026-03-22T00:00:00Z')
                """
            )

    mark_local_action_job_started(
        db_path=db_path,
        busy_timeout_ms=1_000,
        job_id="job-1",
        process_id="process-1",
        payload={
            "accepted_at": "2026-03-22T00:00:00Z",
            "started_at": "2026-03-22T00:00:01Z",
        },
    )
    append_local_action_step_event(
        db_path=db_path,
        busy_timeout_ms=1_000,
        process_id="process-1",
        payload={"step_id": "step-1"},
    )
    append_local_process_event(
        db_path=db_path,
        busy_timeout_ms=1_000,
        process_id="process-1",
        event_type="stream_end",
        payload={"status": "success"},
    )
    assert (
        append_local_action_step_event(
            db_path=db_path,
            busy_timeout_ms=1_000,
            process_id="process-1",
            payload={"step_id": "late-step"},
        )
        is None
    )
    events = read_local_process_events_after(
        db_path=db_path,
        busy_timeout_ms=1_000,
        process_id="process-1",
        after_cursor=0,
        limit=10,
    )

    assert [event.event_type for event in events] == [
        "process_started",
        "action_step",
        "stream_end",
    ]
    assert (
        resolve_local_process_event_cursor(
            db_path=db_path,
            busy_timeout_ms=1_000,
            process_id="process-1",
            event_id=events[0].event_id,
        )
        == events[0].cursor
    )
    assert (
        resolve_local_process_event_cursor(
            db_path=db_path,
            busy_timeout_ms=1_000,
            process_id="process-1",
            event_id="missing-event",
        )
        is None
    )
    import sqlite3

    with sqlite3.connect(db_path) as connection:
        process_status = connection.execute(
            "SELECT status FROM processes WHERE process_id = 'process-1'"
        ).fetchone()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = 'job-1'"
        ).fetchone()
    assert process_status == ("running",)
    assert job_status == ("running",)


def test_local_process_pause_event_roundtrip(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    import sqlite3

    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES ('user-1', 'ja', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z')
                """
            )
            connection.execute(
                """
                INSERT INTO processes(
                    process_id,
                    user_id,
                    kind,
                    status,
                    action_id,
                    started_at,
                    updated_at,
                    heartbeat_at,
                    next_event_seq
                ) VALUES ('process-1', 'user-1', 'action', 'running', 'action-1', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z', '2026-03-22T00:00:00Z', 1)
                """
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id,
                    user_id,
                    job_type,
                    process_id,
                    status,
                    scheduled_at,
                    logical_key
                ) VALUES ('job-1', 'user-1', 'execute_action', 'process-1', 'running', '2026-03-22T00:00:00Z', 'action-1')
                """
            )
            connection.execute(
                "UPDATE processes SET current_job_id = 'job-1' WHERE process_id = 'process-1'"
            )

    pause_payload = {
        "action_id": "action-1",
        "user_id": "user-1",
        "status": "processing",
        "reason": "approval_pending",
        "approval_blockers": [
            {
                "approval_session_id": "approval-1",
                "tool_request_id": "tool-request-1",
            }
        ],
    }
    with pytest.raises(MigrationError, match="one running attempt"):
        mark_local_action_job_paused(
            db_path=db_path,
            busy_timeout_ms=1_000,
            job_id="job-1",
            process_id="process-1",
            payload=pause_payload,
        )
    with sqlite3.connect(db_path) as connection:
        state_after_rollback = connection.execute(
            """
            SELECT jobs.status, processes.status, processes.current_job_id,
                   (SELECT COUNT(*) FROM process_events)
            FROM jobs
            JOIN processes ON processes.process_id = jobs.process_id
            WHERE jobs.job_id = 'job-1'
            """
        ).fetchone()
    assert state_after_rollback == ("running", "running", "job-1", 0)

    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id, job_id, attempt_number, started_at, status
                ) VALUES ('attempt-1', 'job-1', 1, '2026-03-22T00:00:00Z', 'running')
                """
            )

    mark_local_action_job_paused(
        db_path=db_path,
        busy_timeout_ms=1_000,
        job_id="job-1",
        process_id="process-1",
        payload=pause_payload,
    )

    events = read_local_process_events_after(
        db_path=db_path,
        busy_timeout_ms=1_000,
        process_id="process-1",
        after_cursor=0,
        limit=10,
    )

    assert [event.event_type for event in events] == [
        "action_approval_snapshot",
        "process_paused",
    ]
    with sqlite3.connect(db_path) as connection:
        process_status = connection.execute(
            "SELECT status FROM processes WHERE process_id = 'process-1'"
        ).fetchone()
        job_status = connection.execute(
            "SELECT status FROM jobs WHERE job_id = 'job-1'"
        ).fetchone()
        attempt_status = connection.execute(
            "SELECT status FROM job_attempts WHERE attempt_id = 'attempt-1'"
        ).fetchone()
    assert process_status == ("paused",)
    assert job_status == ("paused",)
    assert attempt_status == ("completed",)
