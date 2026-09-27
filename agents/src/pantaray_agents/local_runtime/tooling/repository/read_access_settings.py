from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.schema.read_access import (
    READ_ACCESS_SCOPE_FULL_ACCESS,
    READ_ACCESS_SCOPE_WORKSPACE,
    ReadAccessScope,
)

from ...storage.migrations import MigrationError
from ...storage.users import ensure_user_row
from .common import _configure_connection


def load_read_access_scope(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
) -> ReadAccessScope:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        return load_read_access_scope_in_connection(
            connection=connection,
            user_id=user_id,
        )


def load_read_access_scope_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
) -> ReadAccessScope:
    row = connection.execute(
        """
        SELECT read_access_scope
        FROM read_access_preferences
        WHERE user_id = ?
        """,
        (user_id,),
    ).fetchone()
    if row is None:
        return READ_ACCESS_SCOPE_FULL_ACCESS
    return coerce_read_access_scope(str(row["read_access_scope"]))


def update_read_access_scope(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    read_access_scope: ReadAccessScope,
    now: str,
) -> ReadAccessScope:
    scope = coerce_read_access_scope(read_access_scope)
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=user_id)
            connection.execute(
                """
                INSERT INTO read_access_preferences(
                    user_id,
                    read_access_scope,
                    created_at,
                    updated_at,
                    updated_by
                ) VALUES (?, ?, ?, ?, 'user')
                ON CONFLICT(user_id) DO UPDATE SET
                    read_access_scope = excluded.read_access_scope,
                    updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
                """,
                (user_id, scope, now, now),
            )
    return scope


def coerce_read_access_scope(value: str) -> ReadAccessScope:
    if value == READ_ACCESS_SCOPE_WORKSPACE:
        return READ_ACCESS_SCOPE_WORKSPACE
    if value == READ_ACCESS_SCOPE_FULL_ACCESS:
        return READ_ACCESS_SCOPE_FULL_ACCESS
    raise MigrationError(f"invalid read_access_scope: {value}")


__all__ = [
    "READ_ACCESS_SCOPE_FULL_ACCESS",
    "READ_ACCESS_SCOPE_WORKSPACE",
    "ReadAccessScope",
    "coerce_read_access_scope",
    "load_read_access_scope",
    "load_read_access_scope_in_connection",
    "update_read_access_scope",
]
