from __future__ import annotations

import re
import sqlite3

from .connection import table_exists
from .specs import MigrationError

TEMP_REBUILD_SUFFIX = "__rebuild_v16"
INDEX_NAME_PATTERN = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?INDEX(?:\s+IF\s+NOT\s+EXISTS)?\s+([^\s]+)\s+ON",
    re.IGNORECASE,
)
TRIGGER_NAME_PATTERN = re.compile(
    r"CREATE\s+TRIGGER(?:\s+IF\s+NOT\s+EXISTS)?\s+([^\s]+)\s+",
    re.IGNORECASE,
)
REBUILD_ORDER = {
    "jobs": 5,
    "job_attempts": 6,
    "job_payloads": 7,
    "process_events": 8,
    "action_desires": 10,
    "action_check_items": 20,
    "action_goals": 30,
    "action_requirements": 40,
    "action_completed_goals": 50,
    "agent_actions": 55,
    "agent_action_steps": 60,
    "execution_sessions": 70,
    "tool_invocations": 80,
    "tool_outputs": 90,
    "approval_sessions": 100,
    "file_references": 110,
    "tool_runtime_resources": 120,
    "tool_runtime_resource_events": 130,
    "agent_process_events": 140,
    "agent_suggestion_critics": 150,
    "agent_insights": 160,
}
MAX_REBUILD_PASSES = 5


def rebuild_tables_with_legacy_foreign_keys(
    connection: sqlite3.Connection,
    *,
    legacy_table_names: tuple[str, ...],
    skip_tables: tuple[str, ...] = (),
) -> None:
    for _ in range(MAX_REBUILD_PASSES):
        impacted_tables = _find_impacted_tables(
            connection,
            legacy_table_names=legacy_table_names,
            skip_tables=skip_tables,
        )
        if not impacted_tables:
            drop_rebuild_temp_tables(connection)
            return
        transformed_trigger_sql_by_table = _drop_impacted_table_triggers(
            connection,
            table_names=impacted_tables,
        )
        for table_name in impacted_tables:
            _rebuild_table_with_updated_foreign_keys(
                connection,
                table_name=table_name,
            )
        _recreate_triggers(
            connection,
            transformed_trigger_sql_by_table=transformed_trigger_sql_by_table,
        )
    drop_rebuild_temp_tables(connection)
    raise MigrationError("legacy foreign-key rebuild did not converge")


def drop_legacy_tables(
    connection: sqlite3.Connection,
    *,
    legacy_table_names: tuple[str, ...],
) -> None:
    for table_name in legacy_table_names:
        if table_exists(connection, table_name=table_name):
            connection.execute(f"DROP TABLE {table_name}")


def drop_rebuild_temp_tables(connection: sqlite3.Connection) -> None:
    rows = connection.execute(
        """
        SELECT name
        FROM sqlite_master
        WHERE type = 'table' AND name LIKE ?
        ORDER BY name ASC
        """,
        (f"%{TEMP_REBUILD_SUFFIX}",),
    ).fetchall()
    for row in rows:
        table_name = str(row[0])
        try:
            connection.execute(f'DROP TABLE "{table_name}"')
        except sqlite3.OperationalError as exc:
            if "no such table" not in str(exc):
                raise


def _find_impacted_tables(
    connection: sqlite3.Connection,
    *,
    legacy_table_names: tuple[str, ...],
    skip_tables: tuple[str, ...],
) -> tuple[str, ...]:
    legacy_name_set = set(legacy_table_names)
    skip_name_set = set(skip_tables)
    table_rows = connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name ASC"
    ).fetchall()
    impacted: list[str] = []
    for row in table_rows:
        table_name = str(row[0])
        if (
            table_name in legacy_name_set
            or table_name in skip_name_set
            or table_name.endswith(TEMP_REBUILD_SUFFIX)
        ):
            continue
        foreign_keys = connection.execute(
            f"PRAGMA foreign_key_list('{table_name}')"
        ).fetchall()
        has_impacted_foreign_keys = any(
            _is_impacted_parent(str(foreign_key[2]), legacy_name_set)
            for foreign_key in foreign_keys
        )
        has_impacted_triggers = _table_has_impacted_triggers(
            connection,
            table_name=table_name,
            legacy_table_names=legacy_table_names,
        )
        if has_impacted_foreign_keys or has_impacted_triggers:
            impacted.append(table_name)
    return tuple(sorted(impacted, key=_rebuild_priority))


def _rebuild_table_with_updated_foreign_keys(
    connection: sqlite3.Connection,
    *,
    table_name: str,
) -> None:
    create_sql_row = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = 'table' AND name = ?
        """,
        (table_name,),
    ).fetchone()
    if create_sql_row is None or create_sql_row[0] is None:
        raise MigrationError(f"table schema not found for rebuild target: {table_name}")
    create_sql = str(create_sql_row[0])
    transformed_create_sql = _replace_legacy_table_references(create_sql)
    index_sql_statements = _load_recreatable_sql(
        connection,
        table_name=table_name,
        object_type="index",
    )
    temp_table_name = f"{table_name}{TEMP_REBUILD_SUFFIX}"
    if table_exists(connection, table_name=temp_table_name):
        connection.execute(f'DROP TABLE "{temp_table_name}"')
    connection.execute(f'ALTER TABLE "{table_name}" RENAME TO "{temp_table_name}"')
    connection.execute(transformed_create_sql)
    _copy_all_rows(connection, source_table=temp_table_name, target_table=table_name)
    for index_sql in index_sql_statements:
        _drop_index_if_exists(connection, index_sql=index_sql)
        connection.execute(index_sql)


def _load_recreatable_sql(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    object_type: str,
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE type = ? AND tbl_name = ? AND sql IS NOT NULL
        ORDER BY name ASC
        """,
        (object_type, table_name),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _copy_all_rows(
    connection: sqlite3.Connection,
    *,
    source_table: str,
    target_table: str,
) -> None:
    columns = _table_columns(connection, table_name=target_table)
    quoted_columns = ", ".join(columns)
    connection.execute(
        f'INSERT INTO "{target_table}" ({quoted_columns}) '
        f'SELECT {quoted_columns} FROM "{source_table}"'
    )


def _table_columns(
    connection: sqlite3.Connection, *, table_name: str
) -> tuple[str, ...]:
    rows = connection.execute(f"PRAGMA table_info('{table_name}')").fetchall()
    if not rows:
        raise MigrationError(f"table_info returned no columns for: {table_name}")
    return tuple(str(row[1]) for row in rows)


def _replace_legacy_table_references(
    sql: str,
) -> str:
    rewritten = sql
    for legacy_table_name in _legacy_table_names_in_sql(sql):
        current_table_name = _legacy_table_current_name(legacy_table_name)
        rewritten = rewritten.replace(legacy_table_name, current_table_name)
    while TEMP_REBUILD_SUFFIX in rewritten:
        prefix, suffix = rewritten.split(TEMP_REBUILD_SUFFIX, maxsplit=1)
        rewritten = prefix + suffix
    return rewritten


def _legacy_table_current_name(legacy_table_name: str) -> str:
    marker = "_legacy_v"
    if marker not in legacy_table_name:
        raise MigrationError(f"unsupported legacy table name: {legacy_table_name}")
    return legacy_table_name.split(marker, maxsplit=1)[0]


def _is_impacted_parent(parent_table_name: str, legacy_name_set: set[str]) -> bool:
    return parent_table_name in legacy_name_set or parent_table_name.endswith(
        TEMP_REBUILD_SUFFIX
    )


def _table_has_impacted_triggers(
    connection: sqlite3.Connection,
    *,
    table_name: str,
    legacy_table_names: tuple[str, ...],
) -> bool:
    trigger_sql_statements = _load_recreatable_sql(
        connection,
        table_name=table_name,
        object_type="trigger",
    )
    return any(
        TEMP_REBUILD_SUFFIX in trigger_sql
        or any(
            legacy_table_name in trigger_sql for legacy_table_name in legacy_table_names
        )
        for trigger_sql in trigger_sql_statements
    )


def _rebuild_priority(table_name: str) -> tuple[int, str]:
    return (REBUILD_ORDER.get(table_name, 1_000), table_name)


def _drop_index_if_exists(connection: sqlite3.Connection, *, index_sql: str) -> None:
    match = INDEX_NAME_PATTERN.search(index_sql)
    if match is None:
        return
    raw_index_name = match.group(1).strip()
    index_name = raw_index_name.strip('"')
    connection.execute(f'DROP INDEX IF EXISTS "{index_name}"')


def _drop_trigger_if_exists(
    connection: sqlite3.Connection, *, trigger_sql: str
) -> None:
    match = TRIGGER_NAME_PATTERN.search(trigger_sql)
    if match is None:
        return
    raw_trigger_name = match.group(1).strip()
    trigger_name = raw_trigger_name.strip('"')
    connection.execute(f'DROP TRIGGER IF EXISTS "{trigger_name}"')


def _drop_impacted_table_triggers(
    connection: sqlite3.Connection,
    *,
    table_names: tuple[str, ...],
) -> dict[str, tuple[str, ...]]:
    transformed_trigger_sql_by_table: dict[str, tuple[str, ...]] = {}
    for table_name in table_names:
        trigger_sql_statements = _load_recreatable_sql(
            connection,
            table_name=table_name,
            object_type="trigger",
        )
        transformed_trigger_sql_by_table[table_name] = tuple(
            _replace_legacy_table_references(trigger_sql)
            for trigger_sql in trigger_sql_statements
        )
        for trigger_sql in trigger_sql_statements:
            _drop_trigger_if_exists(connection, trigger_sql=trigger_sql)
    return transformed_trigger_sql_by_table


def _recreate_triggers(
    connection: sqlite3.Connection,
    *,
    transformed_trigger_sql_by_table: dict[str, tuple[str, ...]],
) -> None:
    for trigger_sql_statements in transformed_trigger_sql_by_table.values():
        for trigger_sql in trigger_sql_statements:
            _drop_trigger_if_exists(connection, trigger_sql=trigger_sql)
            connection.execute(trigger_sql)


def _legacy_table_names_in_sql(sql: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            {match.group(0) for match in re.finditer(r"\b[a-z_]+_legacy_v\d+\b", sql)}
        )
    )
