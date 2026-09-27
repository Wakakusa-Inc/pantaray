from __future__ import annotations

import sqlite3

from .action_status_alignment_fk import (
    drop_legacy_tables,
    rebuild_tables_with_legacy_foreign_keys,
)
from .sql_script import execute_sql_statements

LEGACY_REMOVE_INTERVENTION_TABLE_NAMES = (
    "agent_suggestion_history_legacy_v28",
    "agent_suggestions_legacy_v28",
)


def apply_command_invocation_executable_sources_migration(
    connection: sqlite3.Connection,
    *,
    migration_statements: tuple[str, ...],
) -> None:
    rebuild_tables_with_legacy_foreign_keys(
        connection,
        legacy_table_names=LEGACY_REMOVE_INTERVENTION_TABLE_NAMES,
    )
    drop_legacy_tables(
        connection,
        legacy_table_names=LEGACY_REMOVE_INTERVENTION_TABLE_NAMES,
    )
    execute_sql_statements(connection, migration_statements)


__all__ = ["apply_command_invocation_executable_sources_migration"]
