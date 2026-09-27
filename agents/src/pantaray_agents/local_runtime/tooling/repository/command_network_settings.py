"""User-owned command networking; absence alone means the initial ON setting."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from ...storage.users import ensure_user_row
from .common import _configure_connection


def load_command_network_enabled(
    *, db_path: Path, busy_timeout_ms: int, user_id: str
) -> bool:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            "SELECT command_network_enabled FROM command_network_preferences "
            "WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    return True if row is None else bool(row["command_network_enabled"])


def update_command_network_enabled(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    command_network_enabled: bool,
    now: str,
) -> bool:
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=user_id, timestamp=now)
            connection.execute(
                """
                INSERT INTO command_network_preferences(
                    user_id, command_network_enabled, updated_at
                ) VALUES (?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    command_network_enabled = excluded.command_network_enabled,
                    updated_at = excluded.updated_at
                """,
                (user_id, command_network_enabled, now),
            )
    return command_network_enabled
