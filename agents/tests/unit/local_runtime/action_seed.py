from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.storage.users import ensure_user_row


def insert_agent_action(
    *,
    db_path: Path,
    user_id: str = "user-1",
    suggestion_id: str = "suggestion-1",
    action_id: str = "action-1",
    initial_user_message_id: str | None = None,
    created_at: str = "2026-03-23T00:00:00Z",
) -> None:
    message_id = initial_user_message_id or f"message:{action_id}"
    with sqlite3.connect(db_path) as connection:
        with connection:
            ensure_user_row(connection, user_id=user_id, timestamp=created_at)
            connection.execute(
                """
                INSERT OR IGNORE INTO agent_suggestions(
                    suggestion_id,
                    user_id,
                    status,
                    created_at,
                    updated_at
                ) VALUES (?, ?, 'processing', ?, ?)
                """,
                (suggestion_id, user_id, created_at, created_at),
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO agent_actions(
                    action_id,
                    user_id,
                    suggestion_id,
                    initial_user_message_id,
                    execution_target_json,
                    status,
                    final_output,
                    prompt_name,
                    prompt_version,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, '{"kind":"scratch"}',
                          'processing', '', 'test/tooling', 'v1', ?, ?)
                """,
                (
                    action_id,
                    user_id,
                    suggestion_id,
                    message_id,
                    created_at,
                    created_at,
                ),
            )
