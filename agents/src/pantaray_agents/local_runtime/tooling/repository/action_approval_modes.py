from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

from ..models import ApprovalMode
from .common import _configure_connection


class ActionApprovalModeOwnerError(RuntimeError):
    """The Action does not exist or is not owned by the requesting user."""


def load_action_approval_mode(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    action_id: str,
) -> ApprovalMode | None:
    """Return the Action-level override, or None when the default applies."""

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            """
            SELECT approval_mode
            FROM action_approval_modes
            WHERE action_id = ? AND user_id = ?
            """,
            (action_id, user_id),
        ).fetchone()
    if row is None:
        return None
    return cast(ApprovalMode, str(row["approval_mode"]))


def set_action_approval_mode(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    action_id: str,
    approval_mode: ApprovalMode,
    updated_at: str,
) -> None:
    """Record the Action-level override, which is the consent for that Action."""

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            set_action_approval_mode_in_connection(
                connection=connection,
                user_id=user_id,
                action_id=action_id,
                approval_mode=approval_mode,
                updated_at=updated_at,
            )


def set_action_approval_mode_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    approval_mode: ApprovalMode,
    updated_at: str,
) -> None:
    """Persist consent inside the caller's Action transaction."""

    owner_row = connection.execute(
        "SELECT 1 FROM agent_actions WHERE action_id = ? AND user_id = ?",
        (action_id, user_id),
    ).fetchone()
    if owner_row is None:
        raise ActionApprovalModeOwnerError("action does not exist for this user")
    connection.execute(
        """
        INSERT INTO action_approval_modes(
            action_id,
            user_id,
            approval_mode,
            created_at,
            updated_at
        ) VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(action_id) DO UPDATE SET
            approval_mode = excluded.approval_mode,
            updated_at = excluded.updated_at
        """,
        (action_id, user_id, approval_mode, updated_at, updated_at),
    )


__all__ = [
    "ActionApprovalModeOwnerError",
    "load_action_approval_mode",
    "set_action_approval_mode",
    "set_action_approval_mode_in_connection",
]
