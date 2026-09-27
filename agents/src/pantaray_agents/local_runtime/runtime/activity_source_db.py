from __future__ import annotations

import sqlite3
from collections.abc import Callable
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction


def with_activity_source_connection(
    *,
    db_path: Path | str,
    busy_timeout_ms: int,
    operation: Callable[[sqlite3.Connection], None],
    transactional: bool = True,
) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    with sqlite3.connect(str(db_path)) as connection:
        configure_connection(connection, busy_timeout_ms)
        if transactional:
            with immediate_transaction(connection):
                operation(connection)
        else:
            operation(connection)


def require_exactly_one_changed_row(
    connection: sqlite3.Connection,
    *,
    context: str,
) -> None:
    row = connection.execute("SELECT changes()").fetchone()
    if row is None or int(row[0]) != 1:
        raise MigrationError(context)
