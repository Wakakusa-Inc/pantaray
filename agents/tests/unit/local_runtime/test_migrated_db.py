import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import load_default_migrations

from .migrated_db import prepare_test_database


def test_prepared_databases_include_wal_changes_and_are_isolated(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    first = tmp_path / "first.db"
    second = tmp_path / "second.db"
    prepare_test_database(first, 1_000, migrations)
    with sqlite3.connect(first) as connection:
        connection.execute("CREATE TABLE first_only(value TEXT)")

    prepare_test_database(second, 1_000, migrations)
    with sqlite3.connect(second) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()
        first_only = connection.execute(
            "SELECT name FROM sqlite_master WHERE name = 'first_only'"
        ).fetchone()
    assert version == (migrations[-1].version,)
    assert first_only is None


def test_partial_migration_runs_real_migration(tmp_path: Path) -> None:
    db_path = tmp_path / "partial.db"
    first_migration = load_default_migrations()[:1]
    prepare_test_database(db_path, 1_000, first_migration)

    with sqlite3.connect(db_path) as connection:
        version = connection.execute(
            "SELECT current_version FROM schema_versions WHERE component = 'local_runtime'"
        ).fetchone()
    assert version == (first_migration[0].version,)
