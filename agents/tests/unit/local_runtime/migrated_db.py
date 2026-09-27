"""Give runtime behavior tests an isolated copy of the current database schema."""

import sqlite3
from contextlib import closing
from functools import cache
from pathlib import Path
from tempfile import TemporaryDirectory

from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.migrations.specs import MigrationSpec


@cache
def _current_database_image() -> bytes:
    with TemporaryDirectory() as directory:
        migrated = Path(directory) / "migrated.db"
        image = Path(directory) / "image.db"
        apply_migrations(migrated, 1_000, load_default_migrations())
        # The migrated database uses WAL, so copy through SQLite to include it.
        with closing(sqlite3.connect(migrated)) as source:
            with closing(sqlite3.connect(image)) as target:
                source.backup(target)
        return image.read_bytes()


def prepare_test_database(
    db_path: Path, busy_timeout_ms: int, migrations: tuple[MigrationSpec, ...]
) -> None:
    if (
        not db_path.exists()
        and busy_timeout_ms > 0
        and migrations == load_default_migrations()
    ):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_path.write_bytes(_current_database_image())
        return
    apply_migrations(db_path, busy_timeout_ms, migrations)
