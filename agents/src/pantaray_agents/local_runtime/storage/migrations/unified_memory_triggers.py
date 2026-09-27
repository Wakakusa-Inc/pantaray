from __future__ import annotations

import sqlite3

from .action_user_process_ownership import create_action_user_process_triggers
from .specs import MigrationError
from .sql_script import execute_sql_statements


def apply_unified_memory_trigger_migration(
    connection: sqlite3.Connection,
    *,
    migration_statements: tuple[str, ...],
) -> None:
    """Rebuild the trigger ledger and the process kind domain without data loss."""

    process_count = _row_count(connection, table="processes")
    trigger_count = _row_count(connection, table="memory_agent_triggers")
    execute_sql_statements(connection, migration_statements)
    create_action_user_process_triggers(connection)
    if _row_count(connection, table="processes") != process_count:
        raise MigrationError("v99 changed the durable process row count")
    if _row_count(connection, table="memory_agent_triggers") != trigger_count:
        raise MigrationError("v99 changed the durable Memory Agent trigger row count")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            "v99 foreign-key validation failed: "
            f"violations={len(violations)} first={tuple(violations[0])}"
        )


def _row_count(connection: sqlite3.Connection, *, table: str) -> int:
    row = connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()
    if row is None:
        raise MigrationError(f"v99 could not read the durable row count: {table}")
    return int(row[0])
