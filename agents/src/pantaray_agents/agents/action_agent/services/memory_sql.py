from __future__ import annotations

import re
import sqlite3
from collections.abc import Callable
from pathlib import Path
from typing import TypedDict

from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.schema.repositories.repository import (
    JSONValue,
    RepositoryErrorKind,
    RepositoryResult,
)

DEFAULT_MEMORY_SQL_LIMIT = 100
MAX_MEMORY_SQL_LIMIT = 200
MAX_MEMORY_SQL_CELL_CHARS = 4_000
MAX_MEMORY_SQL_OUTPUT_CHARS = 30_000
MEMORY_SQL_PROGRESS_HANDLER_OPCODES = 1_000
MEMORY_SQL_MAX_PROGRESS_CALLBACKS = 20_000
_SQL_IDENTIFIER_PATTERN = re.compile(r"\b[A-Za-z_][A-Za-z0-9_]*\b")
_SQL_SCHEMA_QUALIFIER_PATTERN = re.compile(
    r"\b(?:main|temp|sqlite_master|sqlite_temp_master)\s*\.",
    re.IGNORECASE,
)
_SQL_CTE_NAME_PATTERN = re.compile(
    r"(?:\bWITH\b|,)\s*(?:RECURSIVE\s+)?"
    r"([A-Za-z_][A-Za-z0-9_]*)\s*(?:\([^)]*\)\s*)?\bAS\s*\(",
    re.IGNORECASE,
)
_SQL_FORBIDDEN_SCHEMA_TOKEN = "pragma"
_PRIVATE_VIEW_PREFIX = "__memory_sql_"

MEMORY_SQL_ALLOWED_TABLES = frozenset(
    {
        "activity_logs",
        "activity_summaries",
        "agent_actions",
        "agent_facts",
        "agent_insights",
        "agent_suggestions",
        "source_records",
    }
)

_MEMORY_SQL_USER_SCOPED_TABLES = frozenset(
    {
        "activity_logs",
        "activity_summaries",
        "agent_actions",
        "agent_facts",
        "agent_insights",
        "agent_suggestions",
        "source_records",
    }
)

MEMORY_SQL_BLOCKED_FUNCTIONS = frozenset(
    {
        "format",
        "load_extension",
        "printf",
        "randomblob",
        "sqlite_compileoption_get",
        "sqlite_compileoption_used",
        "sqlite_offset",
        "zeroblob",
    }
)

_ALLOWED_AUTHORIZE_ACTIONS = frozenset(
    {
        sqlite3.SQLITE_FUNCTION,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_SELECT,
    }
)


class MemorySqlPayload(TypedDict):
    columns: list[str]
    rows: list[dict[str, JSONValue]]
    row_count: int
    truncated: bool
    notes: list[str]


class _SerializedRows(TypedDict):
    rows: list[dict[str, JSONValue]]
    truncated: bool


class _ValidatedSql(TypedDict):
    sql: str
    referenced_tables: frozenset[str]


class _ScopedViewPlan(TypedDict):
    public_tables: frozenset[str]
    private_views: frozenset[str]
    private_view_base_tables: dict[str, frozenset[str]]


def run_local_memory_sql(
    *,
    user_id: str,
    sql: str,
    limit: int,
) -> RepositoryResult[MemorySqlPayload]:
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return execute_memory_sql(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        user_id=user_id,
        sql=sql,
        limit=limit,
    )


def execute_memory_sql(
    *,
    db_path: str,
    busy_timeout_ms: int,
    user_id: str,
    sql: str,
    limit: int,
) -> RepositoryResult[MemorySqlPayload]:
    normalized_user_id = user_id.strip()
    if not normalized_user_id:
        return _validation_error("memory_sql: user_id is required.")
    normalized_sql = sql.strip()
    validated_sql = _validate_sql(normalized_sql)
    if isinstance(validated_sql, str):
        return _validation_error(validated_sql)
    normalized_limit = _normalize_limit(limit)

    notes: list[str] = []
    try:
        with _connect_read_only(
            db_path=db_path, busy_timeout_ms=busy_timeout_ms
        ) as conn:
            scoped_view_plan = _install_user_scoped_temp_views(
                conn=conn,
                user_id=normalized_user_id,
                table_names=validated_sql["referenced_tables"],
            )
            progress_count = 0

            def _progress_handler() -> int:
                nonlocal progress_count
                progress_count += 1
                return int(progress_count > MEMORY_SQL_MAX_PROGRESS_CALLBACKS)

            observed_base_reads: set[str] = set()
            conn.set_authorizer(
                _build_memory_sql_authorizer(
                    scoped_view_plan=scoped_view_plan,
                    observed_base_reads=observed_base_reads,
                )
            )
            conn.set_progress_handler(
                _progress_handler,
                MEMORY_SQL_PROGRESS_HANDLER_OPCODES,
            )
            cursor = conn.execute(normalized_sql)
            columns = [description[0] for description in cursor.description or ()]
            raw_rows = cursor.fetchmany(normalized_limit + 1)
            if not observed_base_reads:
                return _validation_error(
                    "memory_sql: query must read at least one allowed memory table."
                )
    except sqlite3.DatabaseError as exc:
        return _validation_error(f"memory_sql rejected query: {exc}")

    truncated = len(raw_rows) > normalized_limit
    serialized = _serialize_rows(
        columns=columns,
        raw_rows=raw_rows[:normalized_limit],
        notes=notes,
    )
    rows = serialized["rows"]
    if serialized["truncated"] or len(rows) < min(len(raw_rows), normalized_limit):
        truncated = True
    return RepositoryResult(
        data={
            "columns": columns,
            "rows": rows,
            "row_count": len(rows),
            "truncated": truncated,
            "notes": notes,
        }
    )


def _connect_read_only(*, db_path: str, busy_timeout_ms: int) -> sqlite3.Connection:
    uri = f"{Path(db_path).resolve().as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.execute(f"PRAGMA busy_timeout = {busy_timeout_ms}")
    conn.row_factory = sqlite3.Row
    return conn


def _install_user_scoped_temp_views(
    *,
    conn: sqlite3.Connection,
    user_id: str,
    table_names: frozenset[str],
) -> _ScopedViewPlan:
    user_id_literal = _quote_sql_literal(user_id)
    private_view_base_tables: dict[str, frozenset[str]] = {}
    for table_name in sorted(table_names & _MEMORY_SQL_USER_SCOPED_TABLES):
        private_view_name = _private_view_name(table_name)
        private_view_base_tables[private_view_name] = frozenset({table_name})
        conn.execute(
            f"""
            CREATE TEMP VIEW {_quote_identifier(private_view_name)} AS
            SELECT *
            FROM main.{_quote_identifier(table_name)}
            WHERE user_id = {user_id_literal}
            """
        )
        _install_public_scoped_view(
            conn=conn,
            public_table_name=table_name,
            private_view_name=private_view_name,
        )
    return {
        "public_tables": table_names,
        "private_views": frozenset(private_view_base_tables),
        "private_view_base_tables": private_view_base_tables,
    }


def _install_public_scoped_view(
    *,
    conn: sqlite3.Connection,
    public_table_name: str,
    private_view_name: str,
) -> None:
    conn.execute(
        f"""
        CREATE TEMP VIEW {_quote_identifier(public_table_name)} AS
        SELECT *
        FROM {_quote_identifier(private_view_name)}
        """
    )


def _private_view_name(table_name: str) -> str:
    return f"{_PRIVATE_VIEW_PREFIX}{table_name}"


def _quote_identifier(identifier: str) -> str:
    escaped = identifier.replace('"', '""')
    return f'"{escaped}"'


def _quote_sql_literal(value: str) -> str:
    escaped = value.replace("'", "''")
    return f"'{escaped}'"


def _validate_sql(sql: str) -> _ValidatedSql | str:
    if not sql:
        return "memory_sql: sql is required."
    if "\x00" in sql:
        return "memory_sql: sql must not contain NUL bytes."
    normalized = sql.strip()
    stripped_statement = _strip_optional_trailing_semicolon(normalized)
    if stripped_statement is None:
        return "memory_sql: only a single SELECT statement is allowed."
    normalized = stripped_statement
    masked_sql = _mask_sql_literals_and_comments(normalized)
    first_token_match = _SQL_IDENTIFIER_PATTERN.search(masked_sql)
    if first_token_match is None:
        return "memory_sql: sql is required."
    first_token = first_token_match.group(0).casefold()
    if first_token not in {"select", "with"}:
        return "memory_sql: only SELECT or WITH ... SELECT is allowed."
    if _SQL_SCHEMA_QUALIFIER_PATTERN.search(masked_sql):
        return "memory_sql: schema-qualified table names are not allowed."
    identifiers = _extract_sql_identifiers(masked_sql)
    if _SQL_FORBIDDEN_SCHEMA_TOKEN in identifiers or any(
        identifier.startswith("sqlite_") for identifier in identifiers
    ):
        return "memory_sql: sqlite internal schema access is not allowed."
    if any(identifier.startswith(_PRIVATE_VIEW_PREFIX) for identifier in identifiers):
        return "memory_sql: internal memory_sql view names are not allowed."
    cte_names = _extract_cte_names(masked_sql)
    if cte_names & MEMORY_SQL_ALLOWED_TABLES:
        return "memory_sql: CTE names must not shadow memory tables."
    referenced_tables = _extract_referenced_memory_tables(masked_sql)
    if not referenced_tables:
        return "memory_sql: query must reference at least one allowed memory table."
    return {"sql": normalized, "referenced_tables": referenced_tables}


def _strip_optional_trailing_semicolon(sql: str) -> str | None:
    masked_sql = _mask_sql_literals_and_comments(sql)
    statement_end = len(masked_sql.rstrip())
    if statement_end == 0:
        return ""
    if masked_sql[statement_end - 1] == ";":
        sql = f"{sql[: statement_end - 1]}{sql[statement_end:]}".strip()
        masked_sql = _mask_sql_literals_and_comments(sql)
    if ";" in masked_sql:
        return None
    return sql.strip()


def _mask_sql_literals_and_comments(sql: str) -> str:
    characters = list(sql)
    index = 0
    while index < len(characters):
        current = characters[index]
        following = characters[index + 1] if index + 1 < len(characters) else ""
        if current == "'":
            index = _mask_quoted_sql(sql=sql, characters=characters, index=index)
            continue
        if current == '"':
            index = _mask_quoted_sql(sql=sql, characters=characters, index=index)
            continue
        if current == "-" and following == "-":
            index = _mask_line_comment(characters=characters, index=index)
            continue
        if current == "/" and following == "*":
            index = _mask_block_comment(sql=sql, characters=characters, index=index)
            continue
        index += 1
    return "".join(characters)


def _mask_quoted_sql(*, sql: str, characters: list[str], index: int) -> int:
    quote = characters[index]
    characters[index] = " "
    index += 1
    while index < len(characters):
        characters[index] = " "
        if sql[index] == quote:
            if index + 1 < len(characters) and sql[index + 1] == quote:
                characters[index + 1] = " "
                index += 2
                continue
            return index + 1
        index += 1
    return index


def _mask_line_comment(*, characters: list[str], index: int) -> int:
    while index < len(characters) and characters[index] not in {"\n", "\r"}:
        characters[index] = " "
        index += 1
    return index


def _mask_block_comment(*, sql: str, characters: list[str], index: int) -> int:
    characters[index] = " "
    characters[index + 1] = " "
    index += 2
    while index < len(characters):
        if sql[index] == "*" and index + 1 < len(characters) and sql[index + 1] == "/":
            characters[index] = " "
            characters[index + 1] = " "
            return index + 2
        characters[index] = " "
        index += 1
    return index


def _extract_sql_identifiers(sql: str) -> frozenset[str]:
    return frozenset(
        match.group(0).casefold() for match in _SQL_IDENTIFIER_PATTERN.finditer(sql)
    )


def _extract_cte_names(sql: str) -> frozenset[str]:
    return frozenset(
        match.group(1).casefold() for match in _SQL_CTE_NAME_PATTERN.finditer(sql)
    )


def _extract_referenced_memory_tables(sql: str) -> frozenset[str]:
    identifiers = _extract_sql_identifiers(sql)
    return frozenset(
        table_name
        for table_name in MEMORY_SQL_ALLOWED_TABLES
        if table_name.casefold() in identifiers
    )


def _normalize_limit(limit: int) -> int:
    if limit <= 0:
        return DEFAULT_MEMORY_SQL_LIMIT
    return min(limit, MAX_MEMORY_SQL_LIMIT)


def _build_memory_sql_authorizer(
    *,
    scoped_view_plan: _ScopedViewPlan,
    observed_base_reads: set[str],
) -> Callable[[int, str | None, str | None, str | None, str | None], int]:
    public_tables = scoped_view_plan["public_tables"]
    private_views = scoped_view_plan["private_views"]
    private_view_base_tables = scoped_view_plan["private_view_base_tables"]
    allowed_temp_objects = public_tables | private_views

    def _authorize_memory_sql(
        action_code: int,
        arg1: str | None,
        arg2: str | None,
        database_name: str | None,
        trigger_or_view_name: str | None,
    ) -> int:
        if action_code not in _ALLOWED_AUTHORIZE_ACTIONS:
            return sqlite3.SQLITE_DENY
        if action_code == sqlite3.SQLITE_READ:
            if database_name == "temp" and arg1 in allowed_temp_objects:
                return sqlite3.SQLITE_OK
            if database_name == "main" and _is_private_view_base_read(
                table_name=arg1,
                trigger_or_view_name=trigger_or_view_name,
                private_view_base_tables=private_view_base_tables,
            ):
                if arg1 is not None:
                    observed_base_reads.add(arg1)
                return sqlite3.SQLITE_OK
            if database_name is None and arg1 in allowed_temp_objects and arg2 == "":
                return sqlite3.SQLITE_OK
            return sqlite3.SQLITE_DENY
        if (
            action_code == sqlite3.SQLITE_FUNCTION
            and (arg2 or "").casefold() in MEMORY_SQL_BLOCKED_FUNCTIONS
        ):
            return sqlite3.SQLITE_DENY
        return sqlite3.SQLITE_OK

    return _authorize_memory_sql


def _is_private_view_base_read(
    *,
    table_name: str | None,
    trigger_or_view_name: str | None,
    private_view_base_tables: dict[str, frozenset[str]],
) -> bool:
    if table_name is None or trigger_or_view_name is None:
        return False
    return table_name in private_view_base_tables.get(trigger_or_view_name, frozenset())


def _serialize_rows(
    *,
    columns: list[str],
    raw_rows: list[sqlite3.Row],
    notes: list[str],
) -> _SerializedRows:
    rows: list[dict[str, JSONValue]] = []
    output_chars = 0
    truncated = False
    for raw_row in raw_rows:
        row: dict[str, JSONValue] = {}
        for column in columns:
            value, cell_truncated = _serialize_value(raw_row[column])
            if cell_truncated:
                truncated = True
            output_chars += len(str(value))
            if output_chars > MAX_MEMORY_SQL_OUTPUT_CHARS:
                notes.append(
                    "memory_sql output was truncated by total character limit."
                )
                return {"rows": rows, "truncated": True}
            row[column] = value
        rows.append(row)
    return {"rows": rows, "truncated": truncated}


def _serialize_value(value: object) -> tuple[JSONValue, bool]:
    if value is None or isinstance(value, bool | int | float):
        return value, False
    if isinstance(value, bytes):
        return f"<bytes {len(value)} bytes>", False
    text = str(value)
    if len(text) <= MAX_MEMORY_SQL_CELL_CHARS:
        return text, False
    return f"{text[: MAX_MEMORY_SQL_CELL_CHARS - 3]}...", True


def _validation_error(message: str) -> RepositoryResult[MemorySqlPayload]:
    return RepositoryResult(
        error=message,
        error_kind=RepositoryErrorKind.VALIDATION,
        retryable=False,
    )


__all__ = [
    "DEFAULT_MEMORY_SQL_LIMIT",
    "MAX_MEMORY_SQL_LIMIT",
    "MEMORY_SQL_ALLOWED_TABLES",
    "MEMORY_SQL_BLOCKED_FUNCTIONS",
    "MemorySqlPayload",
    "execute_memory_sql",
    "run_local_memory_sql",
]
