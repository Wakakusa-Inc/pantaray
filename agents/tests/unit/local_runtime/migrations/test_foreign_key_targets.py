from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
    verify_database_integrity,
)

from .support import _migrations_through

BUSY_TIMEOUT_MS = 1_000
ACTION_APPROVAL_MODES_MIGRATION_NAME = "0103_action_approval_modes.sql"


def _apply_full_schema(db_path: Path) -> None:
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )


def test_every_foreign_key_targets_a_table_that_exists(tmp_path: Path) -> None:
    """SQLite rewrites foreign keys on ALTER TABLE ... RENAME TO.

    A migration that renames a table aside and drops it leaves every table that
    referenced it pointing at the dropped name. The reference stays invisible
    until a row is inserted, and then the startup PRAGMA foreign_key_check
    fails and the local runtime cannot boot.
    """
    db_path = tmp_path / "runtime.db"
    _apply_full_schema(db_path)

    with sqlite3.connect(db_path) as connection:
        table_names = tuple(
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
            )
        )
        dangling = tuple(
            (table_name, str(row[2]))
            for table_name in table_names
            for row in connection.execute(f'PRAGMA foreign_key_list("{table_name}")')
            if str(row[2]) not in table_names
        )

    assert dangling == ()


def test_existing_install_with_a_tool_redactions_row_boots_after_the_drop(
    tmp_path: Path,
) -> None:
    """An install that somehow holds a row must not brick on the next start."""
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=_migrations_through(
            migrations, ACTION_APPROVAL_MODES_MIGRATION_NAME
        ),
    )

    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO tool_redactions(
                    redaction_id, output_id, kind, reason, created_at
                ) VALUES (
                    'redaction-1', 'output-1', 'secret', 'test',
                    '2026-09-08T00:00:00Z'
                )
                """
            )
        violations_before = connection.execute("PRAGMA foreign_key_check").fetchall()

    assert violations_before != []

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    verify_database_integrity(db_path=db_path, busy_timeout_ms=BUSY_TIMEOUT_MS)
