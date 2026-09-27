"""The source records migration must only add to an installed store.

These use the production migration list rather than `support.load_default_migrations`,
which stops below the reset version and would never reach this migration.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    verify_database_integrity,
)
from pantaray_agents.local_runtime.storage.migrations.specs import (
    load_default_migrations,
)

BUSY_TIMEOUT_MS = 5_000
MIGRATION_VERSION = 117
TIMESTAMP = "2026-09-19T00:00:00Z"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    """A store holding one short Insight run, as installed before this version."""
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=tuple(
            migration
            for migration in load_default_migrations()
            if migration.version < MIGRATION_VERSION
        ),
    )
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            connection.execute(
                "INSERT INTO users VALUES ('user-1', 'ja', NULL, ?, ?)",
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute(
                """INSERT INTO activity_logs(log_id, user_id, period_start,
                   period_end, description, status, prompt_name, prompt_version,
                   created_at, updated_at)
                   VALUES ('run-1', 'user-1', ?, ?, '作業の記録', 'success',
                           'insight', '2.2', ?, ?)""",
                (TIMESTAMP, TIMESTAMP, TIMESTAMP, TIMESTAMP),
            )
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    return db_path


def _append(connection: sqlite3.Connection, *, record_id: str, run_id: str) -> None:
    connection.execute(
        """INSERT INTO source_records(record_id, user_id, run_id, event_id,
           observed_at, app_name, bundle_id, window_title, source, speaker,
           shown_time, quote, created_at)
           VALUES (?, 'user-1', ?, 'event-1', ?, 'メッセージ',
                   'com.example.messages', '設計の相談', '設計の相談',
                   'おおたに りん', '09:40', '配色の候補を 3 つ用意しました', ?)""",
        (record_id, run_id, TIMESTAMP, TIMESTAMP),
    )


def test_the_migration_adds_the_table_without_disturbing_an_installed_store(
    db_path: Path,
) -> None:

    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        activity = connection.execute(
            "SELECT description, prompt_version FROM activity_logs WHERE log_id = ?",
            ("run-1",),
        ).fetchone()
        with connection:
            _append(connection, record_id="record-1", run_id="run-1")
        stored = connection.execute(
            "SELECT run_id, quote FROM source_records WHERE record_id = 'record-1'"
        ).fetchone()
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert activity == ("作業の記録", "2.2")
    assert stored == ("run-1", "配色の候補を 3 つ用意しました")
    assert violations == []


def test_a_record_cannot_outlive_the_run_that_produced_it(db_path: Path) -> None:
    """Records are evidence for one activity log; an orphan would claim a source
    no reader can check."""
    with sqlite3.connect(db_path) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        with connection:
            _append(connection, record_id="record-1", run_id="run-1")
        with pytest.raises(sqlite3.IntegrityError):
            with connection:
                _append(connection, record_id="record-2", run_id="run-missing")
        with connection:
            connection.execute("DELETE FROM activity_logs WHERE log_id = 'run-1'")
        remaining = connection.execute("SELECT COUNT(*) FROM source_records").fetchone()

    assert remaining == (0,)


def test_migration_versions_are_unique_and_ordered() -> None:
    """Two branches adding the same number would apply only one of them."""
    versions = [migration.version for migration in load_default_migrations()]

    assert versions == sorted(versions)
    assert len(versions) == len(set(versions))
    assert versions.index(115) < versions.index(116) < versions.index(MIGRATION_VERSION)
