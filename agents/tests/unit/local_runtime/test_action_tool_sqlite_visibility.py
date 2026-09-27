from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.action_conversation.sqlite_visibility import (
    ACTION_TOOL_VISIBILITY_SQL_FUNCTION,
    register_action_tool_visibility_sqlite,
)
from pantaray_agents.schema.action_conversation import (
    visible_action_tool_id_from_step_name,
)


def test_sqlite_visibility_matches_mapper_and_fills_past_hidden_head() -> None:
    candidates = (
        (6, "tool::thinking"),
        (5, "tool::submit_final_answer"),
        (4, "goal_worker::read"),
        (3, "tool::"),
        (2, "tool::read"),
        (1, "tool::write"),
    )
    with sqlite3.connect(":memory:") as connection:
        register_action_tool_visibility_sqlite(connection)
        connection.execute(
            "CREATE TABLE candidate_steps(sort_key INTEGER PRIMARY KEY, step_name TEXT)"
        )
        connection.executemany(
            "INSERT INTO candidate_steps(sort_key, step_name) VALUES (?, ?)",
            candidates,
        )

        mapped_rows = connection.execute(
            f"""
            SELECT step_name, {ACTION_TOOL_VISIBILITY_SQL_FUNCTION}(step_name)
            FROM candidate_steps
            ORDER BY sort_key DESC
            """
        ).fetchall()
        visible_rows = connection.execute(
            f"""
            SELECT step_name, {ACTION_TOOL_VISIBILITY_SQL_FUNCTION}(step_name)
            FROM candidate_steps
            WHERE {ACTION_TOOL_VISIBILITY_SQL_FUNCTION}(step_name) IS NOT NULL
            ORDER BY sort_key DESC
            LIMIT 2
            """
        ).fetchall()

    assert mapped_rows == [
        (step_name, visible_action_tool_id_from_step_name(step_name))
        for _, step_name in candidates
    ]
    assert visible_rows == [("tool::read", "read"), ("tool::write", "write")]
