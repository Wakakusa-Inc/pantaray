from __future__ import annotations

import sqlite3

from .connection import column_exists
from .sql_script import execute_sql_script


def is_agent_suggestions_aligned(connection: sqlite3.Connection) -> bool:
    required_columns = (
        "thinking",
        "prompt_text",
        "response_text",
        "prompt_name",
        "prompt_version",
        "request_images_count",
        "used_images_count",
        "user_reaction",
        "accepted_at",
        "rejected_at",
        "action_status",
        "action_failure_code",
        "action_failure_stage",
        "action_failure_message_public",
        "action_request_payload",
        "action_process_id",
        "action_execution_id",
        "action_command_id",
        "action_started_at",
        "process_event_sequence",
    )
    return all(
        column_exists(
            connection, table_name="agent_suggestions", column_name=column_name
        )
        for column_name in required_columns
    )


def is_agent_actions_aligned(connection: sqlite3.Connection) -> bool:
    required_columns = (
        "error",
        "final_prompt_text",
        "generation",
        "steps_budget",
        "llm_steps_budget",
        "tool_steps_budget",
        "token_budget",
        "total_steps",
        "total_llm_steps",
        "total_tool_steps",
        "total_prompt_tokens",
        "total_completion_tokens",
        "total_tokens",
        "prompt_name",
        "prompt_version",
    )
    return all(
        column_exists(connection, table_name="agent_actions", column_name=column_name)
        for column_name in required_columns
    ) and not column_exists(
        connection, table_name="agent_actions", column_name="command_json"
    )


def is_agent_action_steps_aligned(connection: sqlite3.Connection) -> bool:
    required_columns = (
        "step_id",
        "step_number",
        "step_name",
        "status",
        "short_step_id",
        "user_request_text",
        "tool_args",
        "tool_output",
        "runtime_state_checkpoint",
        "runtime_state_checkpoint_version",
        "error",
    )
    return all(
        column_exists(
            connection, table_name="agent_action_steps", column_name=column_name
        )
        for column_name in required_columns
    ) and not column_exists(
        connection, table_name="agent_action_steps", column_name="action_step_id"
    )


def create_agent_suggestions_table(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE TABLE agent_suggestions (
            suggestion_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('processing', 'success', 'error', 'timeout', 'canceled')
            ),
            answer TEXT,
            thinking TEXT,
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            prompt_text TEXT,
            response_text TEXT,
            prompt_name TEXT,
            prompt_version TEXT,
            has_suggestion INTEGER CHECK (
                has_suggestion IS NULL OR has_suggestion IN (0, 1)
            ),
            request_images_count INTEGER NOT NULL DEFAULT 0 CHECK (request_images_count >= 0),
            used_images_count INTEGER NOT NULL DEFAULT 0 CHECK (used_images_count >= 0),
            interaction_contract TEXT CHECK (
                interaction_contract IS NULL
                OR interaction_contract IN ('action_offer', 'message_only')
            ),
            user_reaction TEXT,
            accepted_at TEXT,
            rejected_at TEXT,
            action_status TEXT CHECK (
                action_status IS NULL
                OR action_status IN (
                    'idle',
                    'processing',
                    'success',
                    'error',
                    'canceled'
                )
            ),
            action_failure_code TEXT,
            action_failure_stage TEXT,
            action_failure_message_public TEXT,
            action_request_payload TEXT CHECK (
                action_request_payload IS NULL OR json_valid(action_request_payload)
            ),
            action_process_id TEXT,
            action_execution_id TEXT,
            action_command_id TEXT,
            action_started_at TEXT,
            process_event_sequence INTEGER NOT NULL DEFAULT 0 CHECK (
                process_event_sequence >= 0
            ),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, suggestion_id),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE
        );
        """,
    )


def create_agent_actions_table(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE TABLE agent_actions (
            action_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            suggestion_id TEXT NOT NULL UNIQUE,
            status TEXT NOT NULL CHECK (
                status IN ('processing', 'success', 'error', 'canceled')
            ),
            final_output TEXT NOT NULL,
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            final_prompt_text TEXT,
            generation INTEGER NOT NULL DEFAULT 1 CHECK (generation >= 1),
            steps_budget INTEGER,
            llm_steps_budget INTEGER,
            tool_steps_budget INTEGER,
            token_budget INTEGER,
            total_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_steps >= 0),
            total_llm_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_llm_steps >= 0),
            total_tool_steps INTEGER NOT NULL DEFAULT 0 CHECK (total_tool_steps >= 0),
            total_prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (
                total_prompt_tokens >= 0
            ),
            total_completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (
                total_completion_tokens >= 0
            ),
            total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
            prompt_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, action_id),
            CHECK (token_budget IS NULL OR token_budget > 0),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (suggestion_id) REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id, suggestion_id) REFERENCES agent_suggestions(user_id, suggestion_id)
        );
        """,
    )


def create_agent_action_steps_table(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE TABLE agent_action_steps (
            step_id TEXT PRIMARY KEY,
            action_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            parent_step_id TEXT,
            step_number INTEGER NOT NULL CHECK (step_number >= 1),
            local_step_number INTEGER,
            short_step_id TEXT,
            step_type TEXT NOT NULL CHECK (
                step_type IN ('user_request', 'llm_output', 'tool_execution')
            ),
            step_name TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'processing', 'success', 'error', 'timeout')
            ),
            goal_handle TEXT,
            requirement_handle TEXT,
            parallel_group_id TEXT,
            parallel_depth INTEGER CHECK (parallel_depth IS NULL OR parallel_depth >= 0),
            parallel_index INTEGER CHECK (parallel_index IS NULL OR parallel_index >= 0),
            retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
            started_at TEXT,
            completed_at TEXT,
            execution_time_ms INTEGER CHECK (
                execution_time_ms IS NULL OR execution_time_ms >= 0
            ),
            prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
            completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
            user_request_text TEXT,
            thinking TEXT,
            llm_prompt_text TEXT,
            llm_response_text TEXT,
            tool_args TEXT CHECK (tool_args IS NULL OR json_valid(tool_args)),
            tool_output TEXT CHECK (tool_output IS NULL OR json_valid(tool_output)),
            runtime_state_checkpoint TEXT CHECK (
                runtime_state_checkpoint IS NULL OR json_valid(runtime_state_checkpoint)
            ),
            runtime_state_checkpoint_version INTEGER CHECK (
                runtime_state_checkpoint_version IS NULL
                OR runtime_state_checkpoint_version >= 1
            ),
            error TEXT CHECK (error IS NULL OR json_valid(error)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (parent_step_id) REFERENCES agent_action_steps(step_id) ON DELETE SET NULL,
            CHECK (local_step_number IS NULL OR local_step_number > 0),
            CHECK (
                (short_step_id IS NULL AND local_step_number IS NULL)
                OR (short_step_id IS NOT NULL AND local_step_number IS NOT NULL)
            ),
            CHECK (short_step_id IS NULL OR LENGTH(short_step_id) <= 128),
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
                OR (
                    step_type IN ('llm_output', 'tool_execution')
                    AND user_request_text IS NULL
                )
            ),
            CHECK (
                (runtime_state_checkpoint IS NULL AND runtime_state_checkpoint_version IS NULL)
                OR (
                    runtime_state_checkpoint IS NOT NULL
                    AND runtime_state_checkpoint_version IS NOT NULL
                )
            )
        );
        """,
    )


def ensure_agent_suggestions_indexes(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_suggestions_user_created
        ON agent_suggestions(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_suggestions_status_updated
        ON agent_suggestions(status, updated_at DESC);
        """,
    )


def ensure_agent_actions_indexes(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_actions_user_created
        ON agent_actions(user_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_agent_actions_suggestion
        ON agent_actions(suggestion_id);
        CREATE INDEX IF NOT EXISTS idx_agent_actions_status_updated
        ON agent_actions(status, updated_at DESC);
        """,
    )


def ensure_agent_action_steps_indexes(connection: sqlite3.Connection) -> None:
    execute_sql_script(
        connection,
        """
        CREATE INDEX IF NOT EXISTS idx_agent_action_steps_action_created
        ON agent_action_steps(action_id, created_at ASC);
        CREATE INDEX IF NOT EXISTS idx_agent_action_steps_short_step_id_resolution
        ON agent_action_steps(
            action_id,
            short_step_id,
            completed_at DESC,
            created_at DESC,
            step_id DESC
        );
        CREATE INDEX IF NOT EXISTS idx_agent_action_steps_goal_handle
        ON agent_action_steps(goal_handle);
        CREATE INDEX IF NOT EXISTS idx_agent_action_steps_requirement_handle
        ON agent_action_steps(requirement_handle);
        """,
    )
