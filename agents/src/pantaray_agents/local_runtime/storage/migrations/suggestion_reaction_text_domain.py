from __future__ import annotations

import sqlite3

from .action_history_schema import (
    create_agent_suggestions_table,
    ensure_agent_suggestions_indexes,
)
from .action_status_alignment_fk import (
    drop_legacy_tables,
    rebuild_tables_with_legacy_foreign_keys,
)
from .connection import table_exists
from .public_event_projection import (
    create_public_history_table,
    ensure_public_history_indexes,
)

LEGACY_SUGGESTIONS_TABLE = "agent_suggestions_legacy_v35"
LEGACY_HISTORY_TABLE = "agent_suggestion_history_legacy_v35"
LEGACY_TABLE_NAMES = (LEGACY_SUGGESTIONS_TABLE, LEGACY_HISTORY_TABLE)
AGENT_SUGGESTIONS_FTS_TABLE = "memory_search_agent_suggestions_fts"


def apply_suggestion_reaction_text_domain_migration(
    connection: sqlite3.Connection,
) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA defer_foreign_keys = ON;")
    if _reaction_text_domain_is_current(connection):
        return
    trigger_sql = (
        *_load_table_trigger_sql(connection, table_name="agent_suggestions"),
        *_load_table_trigger_sql(connection, table_name="agent_suggestion_history"),
    )
    _drop_table_triggers(connection, table_name="agent_suggestions")
    _drop_table_triggers(connection, table_name="agent_suggestion_history")
    _recreate_agent_suggestions_table(connection)
    _rename_public_history_table_to_legacy(connection)
    rebuild_tables_with_legacy_foreign_keys(
        connection,
        legacy_table_names=LEGACY_TABLE_NAMES,
        skip_tables=("agent_suggestions", "agent_suggestion_history"),
    )
    _create_public_history_table_from_legacy(connection)
    drop_legacy_tables(connection, legacy_table_names=LEGACY_TABLE_NAMES)
    ensure_agent_suggestions_indexes(connection)
    if table_exists(connection, table_name="agent_suggestion_history"):
        ensure_public_history_indexes(connection)
    _recreate_triggers(connection, trigger_sql)
    _rebuild_agent_suggestions_fts(connection)


def _reaction_text_domain_is_current(connection: sqlite3.Connection) -> bool:
    table_names = ("agent_suggestions", "agent_suggestion_history")
    if any(table_exists(connection, table_name=name) for name in LEGACY_TABLE_NAMES):
        return False
    for table_name in table_names:
        if not table_exists(connection, table_name=table_name):
            continue
        sql = _load_table_sql(connection, table_name=table_name)
        if "user_reaction TEXT" not in sql:
            return False
        if "user_reaction IS NULL OR user_reaction IN" in sql:
            return False
    return True


def _load_table_sql(connection: sqlite3.Connection, *, table_name: str) -> str:
    row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return "" if row is None or row[0] is None else str(row[0])


def _recreate_agent_suggestions_table(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_suggestions"):
        return
    _drop_table_if_exists(connection, LEGACY_SUGGESTIONS_TABLE)
    connection.execute(
        f"ALTER TABLE agent_suggestions RENAME TO {LEGACY_SUGGESTIONS_TABLE}"
    )
    create_agent_suggestions_table(connection)
    _copy_matching_columns(
        connection,
        source_table=LEGACY_SUGGESTIONS_TABLE,
        target_table="agent_suggestions",
    )


def _rename_public_history_table_to_legacy(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name="agent_suggestion_history"):
        return
    _drop_table_if_exists(connection, LEGACY_HISTORY_TABLE)
    connection.execute(
        f"ALTER TABLE agent_suggestion_history RENAME TO {LEGACY_HISTORY_TABLE}"
    )


def _create_public_history_table_from_legacy(connection: sqlite3.Connection) -> None:
    if not table_exists(connection, table_name=LEGACY_HISTORY_TABLE):
        return
    create_public_history_table(connection)
    _copy_matching_columns(
        connection,
        source_table=LEGACY_HISTORY_TABLE,
        target_table="agent_suggestion_history",
    )


def _copy_matching_columns(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    target_table: str,
) -> None:
    source_columns = set(_table_columns(connection, table_name=source_table))
    target_columns = _table_columns(connection, table_name=target_table)
    columns = tuple(column for column in target_columns if column in source_columns)
    column_list = ", ".join(columns)
    connection.execute(
        f'INSERT INTO "{target_table}" ({column_list}) '
        f'SELECT {column_list} FROM "{source_table}"'
    )


def _table_columns(
    connection: sqlite3.Connection, *, table_name: str
) -> tuple[str, ...]:
    rows = connection.execute(f'PRAGMA table_info("{table_name}")').fetchall()
    return tuple(str(row[1]) for row in rows)


def _drop_table_if_exists(connection: sqlite3.Connection, table_name: str) -> None:
    if table_exists(connection, table_name=table_name):
        connection.execute(f'DROP TABLE "{table_name}"')


def _load_table_trigger_sql(
    connection: sqlite3.Connection,
    *,
    table_name: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'trigger'
          AND tbl_name = ?
          AND sql IS NOT NULL
        ORDER BY name ASC
        """,
        (table_name,),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _drop_table_triggers(connection: sqlite3.Connection, *, table_name: str) -> None:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'trigger'
          AND tbl_name = ?
        ORDER BY name ASC
        """,
        (table_name,),
    ).fetchall()
    for row in rows:
        connection.execute(f'DROP TRIGGER IF EXISTS "{row[0]}"')


def _recreate_triggers(
    connection: sqlite3.Connection,
    trigger_sql_statements: tuple[str, ...],
) -> None:
    for trigger_sql in trigger_sql_statements:
        connection.execute(trigger_sql)


def _rebuild_agent_suggestions_fts(connection: sqlite3.Connection) -> None:
    if table_exists(connection, table_name=AGENT_SUGGESTIONS_FTS_TABLE):
        connection.execute(
            "INSERT INTO memory_search_agent_suggestions_fts"
            "(memory_search_agent_suggestions_fts) VALUES('rebuild')"
        )
