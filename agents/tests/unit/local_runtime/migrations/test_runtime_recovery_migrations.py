from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationError,
    record_runtime_recovery_run,
    repair_inflight_jobs_for_startup,
    verify_database_integrity,
)

from .support import (
    _configure_connection,
    _insert_user,
    apply_migrations,
    load_default_migrations,
)


def test_migration_operations_reject_non_positive_timeout(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"

    with pytest.raises(MigrationError, match="LOCAL_DB_BUSY_TIMEOUT_MS"):
        apply_migrations(
            db_path=db_path,
            busy_timeout_ms=0,
            migrations=load_default_migrations(),
        )
    with pytest.raises(MigrationError, match="LOCAL_DB_BUSY_TIMEOUT_MS"):
        repair_inflight_jobs_for_startup(db_path, 0)
    with pytest.raises(MigrationError, match="LOCAL_DB_BUSY_TIMEOUT_MS"):
        record_runtime_recovery_run(db_path, 0, "startup")


def test_verify_database_integrity_passes_after_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    verify_database_integrity(db_path=db_path, busy_timeout_ms=1_000)


def test_apply_migrations_configures_required_sqlite_pragmas(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    busy_timeout_ms = 1_000
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        journal_mode_row = connection.execute("PRAGMA journal_mode;").fetchone()
        synchronous_row = connection.execute("PRAGMA synchronous;").fetchone()
        wal_autocheckpoint_row = connection.execute(
            "PRAGMA wal_autocheckpoint;"
        ).fetchone()
        busy_timeout_row = connection.execute("PRAGMA busy_timeout;").fetchone()

    assert journal_mode_row is not None
    assert str(journal_mode_row[0]).lower() == "wal"
    assert synchronous_row is not None
    assert int(synchronous_row[0]) == 2
    assert wal_autocheckpoint_row is not None
    assert int(wal_autocheckpoint_row[0]) == 0
    assert busy_timeout_row is not None
    assert int(busy_timeout_row[0]) == busy_timeout_ms


def test_repair_inflight_jobs_for_startup_resets_status(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection, "user-1")
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "process-1",
                    "user-1",
                    "action",
                    "running",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    1,
                ),
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
                    started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-1",
                    "user-1",
                    "execute_action",
                    "process-1",
                    "running",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                ),
            )

    repaired_count = repair_inflight_jobs_for_startup(
        db_path=db_path, busy_timeout_ms=1_000
    )

    with sqlite3.connect(db_path) as connection:
        row = connection.execute(
            """
            SELECT status, claimed_by, claimed_at, heartbeat_at
            FROM jobs
            WHERE job_id = ?
            """,
            ("job-1",),
        ).fetchone()
        process_row = connection.execute(
            """
            SELECT status, current_job_id
            FROM processes
            WHERE process_id = ?
            """,
            ("process-1",),
        ).fetchone()

    assert repaired_count == 1
    assert row is not None
    assert row[0] == "queued"
    assert row[1] is None
    assert row[2] is None
    assert row[3] is None
    assert process_row == ("enqueued", None)


def test_repair_inflight_jobs_for_startup_closes_running_attempts(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection, "user-1")
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
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "process-1",
                    "user-1",
                    "action",
                    "running",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:00Z",
                    1,
                ),
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
                    started_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "job-1",
                    "user-1",
                    "execute_action",
                    "process-1",
                    "running",
                    "2026-03-23T00:00:00Z",
                    "2026-03-23T00:00:01Z",
                ),
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id,
                    job_id,
                    attempt_number,
                    started_at,
                    status
                ) VALUES (?, ?, 1, '2026-03-23T00:00:01Z', 'running')
                """,
                ("attempt-1", "job-1"),
            )

    repair_inflight_jobs_for_startup(db_path=db_path, busy_timeout_ms=1_000)

    with sqlite3.connect(db_path) as connection:
        attempt_row = connection.execute(
            """
            SELECT status, completed_at, error_code
            FROM job_attempts
            WHERE attempt_id = 'attempt-1'
            """
        ).fetchone()

    assert attempt_row is not None
    assert attempt_row[0] == "failed"
    assert attempt_row[1] is not None
    assert attempt_row[2] == "RECOVERY_REQUEUED"


def test_repair_inflight_jobs_for_startup_preserves_blocked_runtime(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            _insert_user(connection, "user-1")
            connection.execute(
                """
                INSERT INTO processes(
                    process_id, user_id, kind, status, current_job_id,
                    started_at, updated_at, heartbeat_at, next_event_seq
                ) VALUES (
                    'process-blocked', 'user-1', 'action', 'running', NULL,
                    '2026-03-23T00:00:00Z', '2026-03-23T00:00:01Z',
                    '2026-03-23T00:00:01Z', 1
                )
                """
            )
            connection.execute(
                """
                INSERT INTO jobs(
                    job_id, user_id, job_type, process_id, status,
                    claimed_by, claimed_at, scheduled_at, started_at,
                    completed_at, error_code
                ) VALUES (
                    'job-blocked', 'user-1', 'execute_action',
                    'process-blocked', 'blocked', 'worker-1',
                    '2026-03-23T00:00:01Z', '2026-03-23T00:00:00Z',
                    '2026-03-23T00:00:01Z', '2026-03-23T00:00:02Z',
                    'LOCAL_JOB_ENVELOPE_INTEGRITY_ERROR'
                )
                """
            )
            connection.execute(
                """
                UPDATE processes
                SET current_job_id = 'job-blocked'
                WHERE process_id = 'process-blocked'
                """
            )
            connection.execute(
                """
                INSERT INTO job_attempts(
                    attempt_id, job_id, attempt_number, started_at, status,
                    completed_at, error_code
                ) VALUES (
                    'attempt-blocked', 'job-blocked', 1,
                    '2026-03-23T00:00:01Z', 'failed',
                    '2026-03-23T00:00:02Z',
                    'LOCAL_JOB_ENVELOPE_INTEGRITY_ERROR'
                )
                """
            )

    repaired_count = repair_inflight_jobs_for_startup(
        db_path=db_path, busy_timeout_ms=1_000
    )

    with sqlite3.connect(db_path) as connection:
        job = connection.execute(
            """
            SELECT status, claimed_by, completed_at, error_code
            FROM jobs WHERE job_id = 'job-blocked'
            """
        ).fetchone()
        process = connection.execute(
            """
            SELECT status, current_job_id
            FROM processes WHERE process_id = 'process-blocked'
            """
        ).fetchone()
        attempt = connection.execute(
            """
            SELECT status, completed_at, error_code
            FROM job_attempts WHERE attempt_id = 'attempt-blocked'
            """
        ).fetchone()

    assert repaired_count == 0
    assert job == (
        "blocked",
        "worker-1",
        "2026-03-23T00:00:02Z",
        "LOCAL_JOB_ENVELOPE_INTEGRITY_ERROR",
    )
    assert process == ("running", "job-blocked")
    assert attempt == (
        "failed",
        "2026-03-23T00:00:02Z",
        "LOCAL_JOB_ENVELOPE_INTEGRITY_ERROR",
    )


def test_record_runtime_recovery_run_inserts_checkpoint(tmp_path: Path) -> None:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=load_default_migrations(),
    )

    recovery_run_id = record_runtime_recovery_run(
        db_path=db_path,
        busy_timeout_ms=1_000,
        note="startup deterministic recovery checkpoint: repaired_inflight_jobs=0",
    )

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT recovery_run_id, status, note FROM runtime_recovery_runs WHERE recovery_run_id = ?",
            (recovery_run_id,),
        ).fetchone()

    assert row is not None
    assert row[0] == recovery_run_id
    assert row[1] == "completed"
    assert "repaired_inflight_jobs=0" in row[2]
