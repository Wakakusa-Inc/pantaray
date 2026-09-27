"""Preserve step identities and schema dependents while admitting assistant messages."""

import sqlite3

from .specs import MigrationError
from .sql_script import execute_sql_statements


def apply_action_assistant_messages_migration(
    connection: sqlite3.Connection, *, migration_statements: tuple[str, ...]
) -> None:
    dependents = connection.execute(
        """SELECT sql FROM sqlite_schema
        WHERE sql IS NOT NULL AND (
            (tbl_name = 'agent_action_steps' AND type IN ('index', 'trigger'))
            OR name = 'trg_action_user_referenced_process_kind'
        ) ORDER BY type, name"""
    ).fetchall()
    (before,) = connection.execute("SELECT COUNT(*) FROM agent_action_steps").fetchone()
    execute_sql_statements(connection, migration_statements)
    for (sql,) in dependents:
        connection.execute(sql)
    (after,) = connection.execute("SELECT COUNT(*) FROM agent_action_steps").fetchone()
    if before != after or connection.execute("PRAGMA foreign_key_check").fetchall():
        raise MigrationError("v107 failed to preserve Action step rows or references")
