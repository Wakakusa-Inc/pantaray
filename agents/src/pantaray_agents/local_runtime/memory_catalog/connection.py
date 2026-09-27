from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)

from .errors import MemoryCatalogIntegrityError


@contextmanager
def open_memory_catalog_connection(
    *, db_path: Path, busy_timeout_ms: int
) -> Iterator[sqlite3.Connection]:
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
    enabled = connection.execute("PRAGMA foreign_keys").fetchone()
    if enabled is None or int(enabled[0]) != 1:
        connection.close()
        raise MemoryCatalogIntegrityError("SQLite foreign key enforcement is required")
    try:
        yield connection
    finally:
        connection.close()
