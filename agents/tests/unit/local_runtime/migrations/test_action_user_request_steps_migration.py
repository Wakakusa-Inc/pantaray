from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from .support import (
    _configure_connection,
    _insert_user,
    _migrations_before,
    _migrations_through,
    apply_migrations,
    load_default_migrations,
)

MIGRATION_NAME = "0073_action_user_request_steps.sql"


def test_action_user_request_step_migration_preserves_rows_and_enforces_shape(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "runtime.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_before(migrations, MIGRATION_NAME),
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        with connection:
            _insert_action_parent_rows(connection)
            _insert_existing_step(connection, step_id="think-1", step_type="llm_output")
            _insert_existing_step(
                connection,
                step_id="tool-1",
                step_type="tool_execution",
                step_number=2,
            )

    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=_migrations_through(migrations, MIGRATION_NAME),
    )

    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection, busy_timeout_ms=1_000)
        columns = {
            row[1]
            for row in connection.execute("PRAGMA table_info(agent_action_steps)")
        }
        preserved = connection.execute(
            """
            SELECT step_id, step_type, user_request_text
            FROM agent_action_steps
            ORDER BY step_number
            """
        ).fetchall()
        indexes = {
            row[1]
            for row in connection.execute("PRAGMA index_list(agent_action_steps)")
        }
        assert "user_request_text" in columns
        assert preserved == [
            ("think-1", "llm_output", None),
            ("tool-1", "tool_execution", None),
        ]

        with connection:
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id, action_id, user_id, step_number, local_step_number,
                    short_step_id, step_type, step_name, status, goal_handle,
                    user_request_text, prompt_tokens, completion_tokens, created_at
                ) VALUES (
                    'user-1', 'action-1', 'user-1', 3, 3,
                    'S-3-USER', 'user_request', 'user_request', 'success', 'S',
                    'Follow-up request', 0, 0, '2026-03-24T00:03:00Z'
                )
                """
            )
        stored_text = connection.execute(
            "SELECT user_request_text FROM agent_action_steps WHERE step_id = 'user-1'"
        ).fetchone()
        assert stored_text == ("Follow-up request",)

        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id, action_id, user_id, step_number, local_step_number,
                    short_step_id, step_type, step_name, status, goal_handle,
                    prompt_tokens, completion_tokens, created_at
                ) VALUES (
                    'bad-user', 'action-1', 'user-1', 4, 4,
                    'S-4-USER', 'user_request', 'user_request', 'success', 'S',
                    0, 0, '2026-03-24T00:04:00Z'
                )
                """
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO agent_action_steps(
                    step_id, action_id, user_id, step_number, local_step_number,
                    short_step_id, step_type, step_name, status, goal_handle,
                    user_request_text, thinking, prompt_tokens, completion_tokens,
                    created_at
                ) VALUES (
                    'mixed-user', 'action-1', 'user-1', 4, 4,
                    'S-4-USER', 'user_request', 'user_request', 'success', 'S',
                    'request', 'not allowed', 0, 0, '2026-03-24T00:04:00Z'
                )
                """
            )

        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert {
            "idx_agent_action_steps_action_created",
            "idx_agent_action_steps_short_step_id_resolution",
            "idx_agent_action_steps_goal_handle",
            "idx_agent_action_steps_requirement_handle",
        } <= indexes


def _insert_action_parent_rows(connection: sqlite3.Connection) -> None:
    _insert_user(connection, "user-1")
    connection.execute(
        """
        INSERT INTO agent_suggestions(
            suggestion_id, user_id, status, answer, prompt_text, response_text,
            prompt_name, prompt_version, has_suggestion, interaction_contract,
            created_at, updated_at
        ) VALUES (
            'suggestion-1', 'user-1', 'success', 'request', 'prompt', 'response',
            'suggestion', '1', 1, 'action_offer',
            '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z'
        )
        """
    )
    connection.execute(
        """
        INSERT INTO agent_actions(
            action_id, user_id, suggestion_id, status, final_output,
            prompt_name, prompt_version, created_at, updated_at
        ) VALUES (
            'action-1', 'user-1', 'suggestion-1', 'processing', '',
            'action/executing', '1',
            '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z'
        )
        """
    )


def _insert_existing_step(
    connection: sqlite3.Connection,
    *,
    step_id: str,
    step_type: str,
    step_number: int = 1,
) -> None:
    suffix = "THINK" if step_type == "llm_output" else "TOOL"
    connection.execute(
        """
        INSERT INTO agent_action_steps(
            step_id, action_id, user_id, step_number, local_step_number,
            short_step_id, step_type, step_name, status, goal_handle,
            prompt_tokens, completion_tokens, created_at
        ) VALUES (?, 'action-1', 'user-1', ?, ?, ?, ?, ?, 'success', 'S', 0, 0, ?)
        """,
        (
            step_id,
            step_number,
            step_number,
            f"S-{step_number}-{suffix}",
            step_type,
            step_id,
            f"2026-03-24T00:0{step_number}:00Z",
        ),
    )
