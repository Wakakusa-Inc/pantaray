from __future__ import annotations

import sqlite3

from .action_user_process_ownership import (
    create_action_user_process_indexes,
    create_action_user_process_triggers,
)
from .specs import MigrationError


def apply_action_user_state_contract_migration(
    connection: sqlite3.Connection,
) -> None:
    if connection.execute("SELECT 1 FROM users LIMIT 1").fetchone():
        raise MigrationError("v89 requires a fresh local runtime")
    connection.execute(_STRICT_ACTION_STEPS_TABLE_SQL)
    connection.execute("DROP TRIGGER trg_action_user_referenced_process_kind")
    connection.execute("DROP TABLE agent_action_steps")
    connection.execute(
        "ALTER TABLE agent_action_steps_v0089 RENAME TO agent_action_steps"
    )
    create_action_user_process_indexes(connection)
    create_action_user_process_triggers(connection)
    connection.execute(
        """
        CREATE INDEX idx_agent_action_steps_action_timeline
        ON agent_action_steps(action_id, step_number DESC, step_id DESC)
        WHERE step_number IS NOT NULL
          AND step_type IN ('user_request', 'tool_execution')
        """
    )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            "v89 foreign-key validation failed: "
            f"violations={len(violations)} first={tuple(violations[0])}"
        )


_STRICT_ACTION_STEPS_TABLE_SQL = """
CREATE TABLE agent_action_steps_v0089 (
    step_id TEXT PRIMARY KEY,
    action_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    parent_step_id TEXT,
    step_number INTEGER CHECK (step_number IS NULL OR step_number >= 1),
    local_step_number INTEGER,
    short_step_id TEXT,
    step_type TEXT NOT NULL CHECK (
        step_type IN ('user_request', 'llm_output', 'tool_execution')),
    step_name TEXT NOT NULL,
    status TEXT NOT NULL CHECK (
        status IN ('queued', 'processing', 'success', 'error', 'timeout')),
    goal_handle TEXT,
    requirement_handle TEXT,
    parallel_group_id TEXT,
    parallel_depth INTEGER CHECK (parallel_depth IS NULL OR parallel_depth >= 0),
    parallel_index INTEGER CHECK (parallel_index IS NULL OR parallel_index >= 0),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    started_at TEXT,
    completed_at TEXT,
    execution_time_ms INTEGER CHECK (execution_time_ms IS NULL OR execution_time_ms >= 0),
    prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
    completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
    user_request_text TEXT,
    user_message_id TEXT,
    user_message_json TEXT CHECK (
        user_message_json IS NULL OR json_valid(user_message_json)),
    thinking TEXT,
    llm_prompt_text TEXT,
    llm_response_text TEXT,
    tool_args TEXT CHECK (tool_args IS NULL OR json_valid(tool_args)),
    tool_output TEXT CHECK (tool_output IS NULL OR json_valid(tool_output)),
    runtime_state_checkpoint TEXT CHECK (
        runtime_state_checkpoint IS NULL OR json_valid(runtime_state_checkpoint)),
    runtime_state_checkpoint_version INTEGER CHECK (
        runtime_state_checkpoint_version IS NULL OR runtime_state_checkpoint_version >= 1),
    error TEXT CHECK (error IS NULL OR json_valid(error)),
    created_at TEXT NOT NULL,
    accepted_sequence INTEGER,
    adoption_canceled_at TEXT,
    expected_process_id TEXT,
    adopted_process_id TEXT,
    FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (parent_step_id) REFERENCES agent_action_steps_v0089(step_id) ON DELETE SET NULL,
    FOREIGN KEY (user_id, action_id, expected_process_id) REFERENCES processes(user_id, action_id, process_id) ON DELETE RESTRICT,
    FOREIGN KEY (user_id, action_id, adopted_process_id) REFERENCES processes(user_id, action_id, process_id) ON DELETE RESTRICT,
    CHECK (local_step_number IS NULL OR local_step_number > 0),
    CHECK ((short_step_id IS NULL AND local_step_number IS NULL)
        OR (short_step_id IS NOT NULL AND local_step_number IS NOT NULL)),
    CHECK (short_step_id IS NULL OR LENGTH(short_step_id) <= 128),
    CHECK (step_type = 'user_request' OR step_number IS NOT NULL),
    CHECK (
        step_type <> 'user_request'
        OR (
            goal_handle = 'S'
            AND (
                (step_number IS NULL AND local_step_number IS NULL AND short_step_id IS NULL)
                OR (
                    step_number IS NOT NULL
                    AND local_step_number IS NOT NULL
                    AND short_step_id = 'S-' || local_step_number || '-USER'
                )
            )
        )
    ),
    CHECK (
        (
            step_type = 'user_request'
            AND user_request_text IS NOT NULL
            AND LENGTH(TRIM(user_request_text)) > 0
            AND thinking IS NULL
            AND llm_prompt_text IS NULL
            AND llm_response_text IS NULL
            AND tool_args IS NULL
            AND tool_output IS NULL
        )
        OR (step_type IN ('llm_output', 'tool_execution') AND user_request_text IS NULL)
    ),
    CHECK (
        (user_message_id IS NULL AND user_message_json IS NULL)
        OR (
            step_type = 'user_request'
            AND user_message_id IS NOT NULL
            AND LENGTH(TRIM(user_message_id)) > 0
            AND user_message_json IS NOT NULL
        )
    ),
    CHECK (
        (runtime_state_checkpoint IS NULL AND runtime_state_checkpoint_version IS NULL)
        OR (
            runtime_state_checkpoint IS NOT NULL
            AND runtime_state_checkpoint_version IS NOT NULL
        )
    ),
    CHECK (
        accepted_sequence IS NULL
        OR (
            step_type = 'user_request'
            AND accepted_sequence > 0
            AND typeof(accepted_sequence) = 'integer'
        )
    ),
    CHECK (
        step_type = 'user_request'
        OR (
            adoption_canceled_at IS NULL
            AND expected_process_id IS NULL
            AND adopted_process_id IS NULL
        )
    ),
    CHECK (
        step_type <> 'user_request'
        OR (
            accepted_sequence IS NOT NULL
            AND (
                (
                    step_number IS NOT NULL
                    AND local_step_number IS NOT NULL
                    AND short_step_id IS NOT NULL
                    AND adoption_canceled_at IS NULL
                    AND adopted_process_id IS NOT NULL
                )
                OR (
                    step_number IS NULL
                    AND local_step_number IS NULL
                    AND short_step_id IS NULL
                    AND adoption_canceled_at IS NULL
                    AND expected_process_id IS NOT NULL
                    AND adopted_process_id IS NULL
                )
                OR (
                    step_number IS NULL
                    AND local_step_number IS NULL
                    AND short_step_id IS NULL
                    AND adoption_canceled_at IS NOT NULL
                    AND expected_process_id IS NOT NULL
                    AND adopted_process_id IS NULL
                )
            )
        )
    )
)
"""
