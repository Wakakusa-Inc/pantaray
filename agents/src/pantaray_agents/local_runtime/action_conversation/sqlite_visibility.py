"""SQLite registration for canonical Action tool visibility."""

from __future__ import annotations

import sqlite3
from typing import Final

from pantaray_agents.schema.action_conversation import (
    visible_action_tool_id_from_step_name,
)

ACTION_TOOL_VISIBILITY_SQL_FUNCTION: Final[str] = "pantaray_visible_action_tool_id"


def register_action_tool_visibility_sqlite(
    connection: sqlite3.Connection,
) -> None:
    """Register the visibility projection for this connection's lifetime."""

    connection.create_function(
        ACTION_TOOL_VISIBILITY_SQL_FUNCTION,
        1,
        visible_action_tool_id_from_step_name,
        deterministic=True,
    )


__all__ = [
    "ACTION_TOOL_VISIBILITY_SQL_FUNCTION",
    "register_action_tool_visibility_sqlite",
]
