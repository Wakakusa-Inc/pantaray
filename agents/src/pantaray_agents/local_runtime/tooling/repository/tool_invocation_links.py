from __future__ import annotations

import sqlite3

from ...storage.migrations import MigrationError


def link_tool_invocation_to_action_step_in_connection(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    invocation_id: str,
    step_id: str,
) -> None:
    step_row = connection.execute(
        """
        SELECT step_id
        FROM agent_action_steps
        WHERE action_id = ?
          AND step_id = ?
        LIMIT 1
        """,
        (action_id, step_id),
    ).fetchone()
    if step_row is None:
        raise MigrationError("tool invocation link failed: action step not found")

    invocation_row = connection.execute(
        """
        SELECT action_id, step_id
        FROM tool_invocations
        WHERE invocation_id = ?
        """,
        (invocation_id,),
    ).fetchone()
    if invocation_row is None:
        raise MigrationError("tool invocation link failed: invocation row not found")
    if invocation_row["action_id"] != action_id:
        raise MigrationError("tool invocation link failed: action mismatch")

    current_step_id = invocation_row["step_id"]
    if current_step_id == step_id:
        return
    if current_step_id is not None:
        raise MigrationError("tool invocation link failed: already linked")

    cursor = connection.execute(
        """
        UPDATE tool_invocations
        SET step_id = ?
        WHERE invocation_id = ?
          AND step_id IS NULL
        """,
        (step_id, invocation_id),
    )
    if cursor.rowcount != 1:
        raise MigrationError(
            "tool invocation link failed: expected exactly one invocation row"
        )


def link_tool_invocations_to_action_step_in_connection(
    connection: sqlite3.Connection,
    *,
    action_id: str,
    invocation_ids: tuple[str, ...],
    step_id: str,
) -> None:
    if len(set(invocation_ids)) != len(invocation_ids):
        raise MigrationError("tool invocation link failed: duplicate invocation id")
    for invocation_id in invocation_ids:
        link_tool_invocation_to_action_step_in_connection(
            connection,
            action_id=action_id,
            invocation_id=invocation_id,
            step_id=step_id,
        )


__all__ = [
    "link_tool_invocation_to_action_step_in_connection",
    "link_tool_invocations_to_action_step_in_connection",
]
