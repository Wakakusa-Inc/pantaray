import sqlite3

from .action_user_process_ownership import create_action_user_process_triggers
from .specs import MigrationError
from .sql_script import execute_sql_statements


def apply_action_subagent_processes_migration(
    connection: sqlite3.Connection,
    *,
    migration_statements: tuple[str, ...],
) -> None:
    source_count = _process_count(connection)
    execute_sql_statements(connection, migration_statements)
    create_action_user_process_triggers(connection)
    if _process_count(connection) != source_count:
        raise MigrationError("v93 changed the durable process row count")
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            "v93 foreign-key validation failed: "
            f"violations={len(violations)} first={tuple(violations[0])}"
        )


def _process_count(connection: sqlite3.Connection) -> int:
    row = connection.execute("SELECT COUNT(*) FROM processes").fetchone()
    if row is None:
        raise MigrationError("v93 could not read the durable process count")
    return int(row[0])
