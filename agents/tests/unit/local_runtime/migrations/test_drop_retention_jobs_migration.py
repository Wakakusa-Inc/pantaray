from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import load_default_migrations

from .support import _migrations_before, _migrations_through, apply_migrations

MIGRATION_NAME = "0105_drop_retention_jobs.sql"
BUSY_TIMEOUT_MS = 1_000


def _table_names(db_path: Path) -> set[str]:
    with closing(sqlite3.connect(db_path)) as connection:
        return {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }


def test_retention_jobs_is_dropped(tmp_path: Path) -> None:
    migrations = load_default_migrations()
    before_path = tmp_path / "before.db"
    after_path = tmp_path / "after.db"

    apply_migrations(
        db_path=before_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    apply_migrations(
        db_path=after_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(migrations, MIGRATION_NAME),
    )

    assert "retention_jobs" in _table_names(before_path)
    assert "retention_jobs" not in _table_names(after_path)
