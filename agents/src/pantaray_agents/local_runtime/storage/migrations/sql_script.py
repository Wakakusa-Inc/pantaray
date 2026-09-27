from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

_LEADING_SQL_COMMENT = re.compile(
    r"\A\s*(?:--[^\n]*(?:\n|\Z)|/\*.*?\*/)",
    flags=re.DOTALL,
)


@dataclass(frozen=True, slots=True)
class PreparedSqlScript:
    statements: tuple[str, ...]
    requires_foreign_keys_disabled: bool


class SqlScriptContractError(ValueError):
    """Raised when a migration script violates runner-owned transaction rules."""


def prepare_sql_script(
    sql: str,
    *,
    strip_transaction_control: bool = False,
) -> PreparedSqlScript:
    """Split a SQLite script without allowing it to own the transaction."""

    statements = _split_sql_statements(sql)
    executable: list[str] = []
    foreign_keys_disabled = False
    for statement in statements:
        normalized = _normalize_control_statement(statement)
        if normalized == "PRAGMA FOREIGN_KEYS = OFF":
            foreign_keys_disabled = True
            continue
        if normalized == "PRAGMA FOREIGN_KEYS = ON":
            continue
        if normalized in {
            "BEGIN",
            "BEGIN DEFERRED",
            "BEGIN IMMEDIATE",
            "BEGIN EXCLUSIVE",
        }:
            if strip_transaction_control:
                continue
            raise SqlScriptContractError(
                "Migration scripts must not start their own transaction."
            )
        if normalized in {"COMMIT", "END", "ROLLBACK"}:
            if strip_transaction_control:
                continue
            raise SqlScriptContractError(
                "Migration scripts must not finish their own transaction."
            )
        executable.append(statement)
    return PreparedSqlScript(
        statements=tuple(executable),
        requires_foreign_keys_disabled=foreign_keys_disabled,
    )


def execute_sql_statements(
    connection: sqlite3.Connection,
    statements: tuple[str, ...],
) -> None:
    for statement in statements:
        connection.execute(statement)


def execute_sql_script(connection: sqlite3.Connection, sql: str) -> None:
    prepared = prepare_sql_script(sql)
    if prepared.requires_foreign_keys_disabled:
        raise SqlScriptContractError(
            "Foreign-key mode can only be changed by the migration runner."
        )
    execute_sql_statements(connection, prepared.statements)


def _split_sql_statements(sql: str) -> tuple[str, ...]:
    statements: list[str] = []
    buffer: list[str] = []
    for character in sql:
        buffer.append(character)
        if character != ";":
            continue
        candidate = "".join(buffer)
        if not sqlite3.complete_statement(candidate):
            continue
        if _contains_sql(candidate):
            statements.append(candidate.strip())
        buffer.clear()

    remainder = "".join(buffer)
    if _contains_sql(remainder):
        raise SqlScriptContractError(
            "Migration script ends with an incomplete SQL statement."
        )
    return tuple(statements)


def _contains_sql(value: str) -> bool:
    lines = (line.split("--", maxsplit=1)[0].strip() for line in value.splitlines())
    return any(lines)


def _normalize_control_statement(statement: str) -> str:
    value = statement
    while match := _LEADING_SQL_COMMENT.match(value):
        value = value[match.end() :]
    return " ".join(value.strip().rstrip(";").split()).upper()
