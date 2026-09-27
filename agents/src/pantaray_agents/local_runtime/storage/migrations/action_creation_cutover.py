from __future__ import annotations

import sqlite3

from .action_creation_cutover_experience import (
    AGENT_EXPERIENCE_RUN_COLUMNS,
    rebuild_agent_experience_extraction_runs,
)
from .action_creation_cutover_inflight import (
    converge_inflight_actions_for_cutover,
)
from .action_creation_cutover_suggestions import (
    AGENT_SUGGESTION_COLUMNS,
    rebuild_agent_suggestions,
    require_canonical_suggestion_links,
)
from .specs import MigrationError

_LEGACY_EXECUTION_TARGET_JSON = '{"kind":"scratch"}'
_INITIAL_USER_MESSAGE_ID_SQL = """
CASE
    WHEN suggestions.action_command_id IS NULL
      OR LENGTH(TRIM(suggestions.action_command_id)) = 0
    THEN 'action:' || actions.action_id
    ELSE suggestions.action_command_id
END
"""
_TERMINAL_ACTION_STATUSES = ("success", "error", "canceled")
_ACTIVE_ACTION_JOB_STATUSES = (
    "queued",
    "running",
    "paused",
    "retryable_error",
    "blocked",
)
_ACTIVE_ACTION_PROCESS_STATUSES = ("enqueued", "running", "paused")

_ACTION_COLUMNS = tuple(
    """action_id user_id suggestion_id status final_output error final_prompt_text
    generation steps_budget llm_steps_budget tool_steps_budget token_budget total_steps
    total_llm_steps total_tool_steps total_prompt_tokens total_completion_tokens
    total_tokens prompt_name prompt_version created_at updated_at""".split()
)
_ACTION_STEP_COLUMNS = tuple(
    """step_id action_id user_id parent_step_id step_number local_step_number
    short_step_id step_type step_name status goal_handle requirement_handle
    parallel_group_id parallel_depth parallel_index retry_count started_at completed_at
    execution_time_ms prompt_tokens completion_tokens user_request_text thinking
    llm_prompt_text llm_response_text tool_args tool_output runtime_state_checkpoint
    runtime_state_checkpoint_version error created_at""".split()
)
_PROCESS_EVENT_COLUMNS = tuple(
    "event_id suggestion_id user_id action_id sequence event_name payload created_at".split()
)


def apply_action_creation_cutover_migration(connection: sqlite3.Connection) -> None:
    _require_source_schema(connection)
    _require_runtime_resource_ownership(connection)
    converge_inflight_actions_for_cutover(connection)
    _run_preflight(connection)

    action_schema_objects = _load_schema_objects(connection, "agent_actions")
    step_schema_objects = _load_schema_objects(connection, "agent_action_steps")
    event_schema_objects = _load_schema_objects(connection, "agent_process_events")

    _rebuild_agent_actions(connection)
    rebuild_agent_suggestions(connection)
    _restore_schema_objects(connection, action_schema_objects)
    _rebuild_agent_action_steps(connection)
    _restore_schema_objects(connection, step_schema_objects)
    _rebuild_agent_process_events(connection)
    _restore_schema_objects(connection, event_schema_objects)
    rebuild_agent_experience_extraction_runs(connection)
    connection.execute(
        """
        CREATE UNIQUE INDEX uq_agent_action_steps_user_message
        ON agent_action_steps(user_id, user_message_id)
        WHERE user_message_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE UNIQUE INDEX uq_agent_process_events_standalone_sequence
        ON agent_process_events(action_id, sequence)
        WHERE suggestion_id IS NULL AND action_id IS NOT NULL
        """
    )
    violations = connection.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise MigrationError(
            "v82 foreign-key validation failed: "
            f"violations={len(violations)} first={tuple(violations[0])}"
        )


def _require_source_schema(connection: sqlite3.Connection) -> None:
    expected_tables = (
        ("agent_suggestions", AGENT_SUGGESTION_COLUMNS),
        ("agent_actions", _ACTION_COLUMNS),
        ("agent_action_steps", _ACTION_STEP_COLUMNS),
        ("agent_process_events", _PROCESS_EVENT_COLUMNS),
        ("agent_experience_extraction_runs", AGENT_EXPERIENCE_RUN_COLUMNS),
    )
    for table_name, expected_columns in expected_tables:
        actual_columns = tuple(
            str(row[1])
            for row in connection.execute(f'PRAGMA table_info("{table_name}")')
        )
        if actual_columns != expected_columns:
            raise MigrationError(
                "v82 source schema mismatch: "
                f"table={table_name} expected={expected_columns} actual={actual_columns}"
            )


def _run_preflight(connection: sqlite3.Connection) -> None:
    checks = (
        (
            "accepted_suggestion",
            """
            SELECT suggestion_id, COALESCE(action_status, 'missing')
            FROM agent_suggestions
            WHERE user_reaction = 'accepted'
              AND (
                  action_status IS NULL
                  OR action_status NOT IN ('success', 'error', 'canceled')
                  OR action_request_payload IS NOT NULL
              )
            ORDER BY suggestion_id
            LIMIT 1
            """,
        ),
        (
            "action",
            f"""
            SELECT action_id, status
            FROM agent_actions
            WHERE status NOT IN ({_placeholders(_TERMINAL_ACTION_STATUSES)})
            ORDER BY action_id
            LIMIT 1
            """,
            _TERMINAL_ACTION_STATUSES,
        ),
        (
            "action_job",
            f"""
            SELECT job_id, status
            FROM jobs
            WHERE job_type = 'execute_action'
              AND status IN ({_placeholders(_ACTIVE_ACTION_JOB_STATUSES)})
            ORDER BY job_id
            LIMIT 1
            """,
            _ACTIVE_ACTION_JOB_STATUSES,
        ),
        (
            "action_process",
            f"""
            SELECT process_id, status
            FROM processes
            WHERE kind = 'action'
              AND status IN ({_placeholders(_ACTIVE_ACTION_PROCESS_STATUSES)})
            ORDER BY process_id
            LIMIT 1
            """,
            _ACTIVE_ACTION_PROCESS_STATUSES,
        ),
        (
            "action_attempt",
            """
            SELECT attempts.attempt_id, attempts.status
            FROM job_attempts AS attempts
            JOIN jobs ON jobs.job_id = attempts.job_id
            WHERE jobs.job_type = 'execute_action'
              AND attempts.status = 'running'
            ORDER BY attempts.attempt_id
            LIMIT 1
            """,
        ),
        (
            "approval",
            """
            SELECT approval_session_id, status
            FROM approval_sessions
            WHERE status = 'pending'
            ORDER BY approval_session_id
            LIMIT 1
            """,
        ),
        (
            "tool_invocation",
            """
            SELECT invocation_id, status
            FROM tool_invocations
            WHERE status IN ('queued', 'running')
            ORDER BY invocation_id
            LIMIT 1
            """,
        ),
        (
            "execution_session",
            """
            SELECT execution_session_id, status
            FROM execution_sessions
            WHERE action_id IS NOT NULL AND status = 'running'
            ORDER BY execution_session_id
            LIMIT 1
            """,
        ),
    )
    for check in checks:
        category = check[0]
        query = check[1]
        parameters = check[2] if len(check) == 3 else ()
        row = connection.execute(query, parameters).fetchone()
        if row is not None:
            raise MigrationError(
                "v82 preflight blocked: "
                f"category={category} id={row[0]} status={row[1]}"
            )
    require_canonical_suggestion_links(connection)
    _require_unique_initial_user_message_ids(connection)


def _require_unique_initial_user_message_ids(
    connection: sqlite3.Connection,
) -> None:
    row = connection.execute(
        f"""
        WITH derived AS (
            SELECT
                actions.user_id,
                actions.action_id,
                {_INITIAL_USER_MESSAGE_ID_SQL} AS initial_user_message_id
            FROM agent_actions AS actions
            JOIN agent_suggestions AS suggestions
              ON suggestions.user_id = actions.user_id
             AND suggestions.suggestion_id = actions.suggestion_id
        )
        SELECT user_id, initial_user_message_id, GROUP_CONCAT(action_id)
        FROM derived
        GROUP BY user_id, initial_user_message_id
        HAVING COUNT(*) > 1
        ORDER BY user_id, initial_user_message_id
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        raise MigrationError(
            "v82 preflight blocked: category=initial_user_message_identity "
            f"id={row[0]}/{row[1]} status=duplicate_actions:{row[2]}"
        )


def _require_runtime_resource_ownership(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        """
        SELECT resources.resource_id
        FROM tool_runtime_resources AS resources
        JOIN execution_sessions AS sessions
          ON sessions.execution_session_id = resources.execution_session_id
        LEFT JOIN tool_invocations AS invocations
          ON invocations.invocation_id = resources.tool_invocation_id
        LEFT JOIN agent_actions AS direct_actions
          ON direct_actions.action_id = resources.action_id
        LEFT JOIN agent_actions AS session_actions
          ON session_actions.action_id = sessions.action_id
        WHERE resources.status IN ('active', 'cleanup_failed')
          AND COALESCE(resources.action_id, sessions.action_id) IS NOT NULL
          AND (
              direct_actions.action_id IS NULL AND resources.action_id IS NOT NULL
              OR session_actions.action_id IS NULL AND sessions.action_id IS NOT NULL
              OR resources.action_id IS NOT NULL
                 AND sessions.action_id IS NOT NULL
                 AND resources.action_id != sessions.action_id
              OR sessions.user_id != COALESCE(
                  direct_actions.user_id, session_actions.user_id
              )
              OR resources.tool_invocation_id IS NOT NULL
                 AND (
                     invocations.invocation_id IS NULL
                     OR invocations.execution_session_id != resources.execution_session_id
                     OR invocations.action_id != COALESCE(
                         resources.action_id, sessions.action_id
                     )
                 )
          )
        ORDER BY resources.resource_id
        LIMIT 1
        """
    ).fetchone()
    if row is not None:
        raise MigrationError(
            "v82 preflight blocked: category=runtime_resource "
            f"id={row[0]} status=owner_mismatch"
        )


def _rebuild_agent_actions(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS agent_actions_v0082")
    connection.execute(
        """
        CREATE TABLE agent_actions_v0082 (
            action_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            suggestion_id TEXT UNIQUE,
            initial_user_message_id TEXT NOT NULL,
            status TEXT NOT NULL CHECK (
                status IN ('queued', 'processing', 'success', 'error', 'canceled')
            ),
            execution_target_json TEXT NOT NULL CHECK (json_valid(execution_target_json)),
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
            total_prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_prompt_tokens >= 0),
            total_completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_completion_tokens >= 0),
            total_tokens INTEGER NOT NULL DEFAULT 0 CHECK (total_tokens >= 0),
            prompt_name TEXT NOT NULL,
            prompt_version TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE (user_id, action_id),
            UNIQUE (user_id, initial_user_message_id),
            CHECK (LENGTH(TRIM(initial_user_message_id)) > 0),
            CHECK (token_budget IS NULL OR token_budget > 0),
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (suggestion_id)
                REFERENCES agent_suggestions(suggestion_id) ON DELETE RESTRICT,
            FOREIGN KEY (user_id, suggestion_id)
                REFERENCES agent_suggestions(user_id, suggestion_id) ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        f"""
        INSERT INTO agent_actions_v0082(
            rowid, action_id, user_id, suggestion_id, initial_user_message_id,
            status, execution_target_json, final_output, error,
            final_prompt_text, generation, steps_budget, llm_steps_budget,
            tool_steps_budget, token_budget, total_steps, total_llm_steps,
            total_tool_steps, total_prompt_tokens, total_completion_tokens,
            total_tokens, prompt_name, prompt_version, created_at, updated_at
        )
        SELECT
            actions.rowid,
            actions.action_id,
            actions.user_id,
            actions.suggestion_id,
            {_INITIAL_USER_MESSAGE_ID_SQL},
            actions.status,
            ?,
            actions.final_output,
            actions.error,
            actions.final_prompt_text,
            actions.generation,
            actions.steps_budget,
            actions.llm_steps_budget,
            actions.tool_steps_budget,
            actions.token_budget,
            actions.total_steps,
            actions.total_llm_steps,
            actions.total_tool_steps,
            actions.total_prompt_tokens,
            actions.total_completion_tokens,
            actions.total_tokens,
            actions.prompt_name,
            actions.prompt_version,
            actions.created_at,
            actions.updated_at
        FROM agent_actions AS actions
        JOIN agent_suggestions AS suggestions
          ON suggestions.user_id = actions.user_id
         AND suggestions.suggestion_id = actions.suggestion_id
        ORDER BY actions.action_id
        """,
        (_LEGACY_EXECUTION_TARGET_JSON,),
    )
    _replace_table(connection, "agent_actions", "agent_actions_v0082")


def _rebuild_agent_action_steps(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS agent_action_steps_v0082")
    connection.execute(
        """
        CREATE TABLE agent_action_steps_v0082 (
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
            execution_time_ms INTEGER CHECK (execution_time_ms IS NULL OR execution_time_ms >= 0),
            prompt_tokens INTEGER NOT NULL DEFAULT 0 CHECK (prompt_tokens >= 0),
            completion_tokens INTEGER NOT NULL DEFAULT 0 CHECK (completion_tokens >= 0),
            user_request_text TEXT,
            user_message_id TEXT,
            user_message_json TEXT CHECK (
                user_message_json IS NULL OR json_valid(user_message_json)
            ),
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
            FOREIGN KEY (parent_step_id)
                REFERENCES agent_action_steps(step_id) ON DELETE SET NULL,
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
            )
        )
        """
    )
    legacy_columns = ", ".join(_ACTION_STEP_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO agent_action_steps_v0082(
            step_id, action_id, user_id, parent_step_id, step_number,
            local_step_number, short_step_id, step_type, step_name, status,
            goal_handle, requirement_handle, parallel_group_id, parallel_depth,
            parallel_index, retry_count, started_at, completed_at,
            execution_time_ms, prompt_tokens, completion_tokens,
            user_request_text, thinking, llm_prompt_text, llm_response_text,
            tool_args, tool_output, runtime_state_checkpoint,
            runtime_state_checkpoint_version, error, created_at
        )
        SELECT {legacy_columns}
        FROM agent_action_steps
        ORDER BY step_id
        """
    )
    _replace_table(connection, "agent_action_steps", "agent_action_steps_v0082")


def _rebuild_agent_process_events(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS agent_process_events_v0082")
    connection.execute(
        """
        CREATE TABLE agent_process_events_v0082 (
            event_id TEXT PRIMARY KEY,
            suggestion_id TEXT,
            user_id TEXT NOT NULL,
            action_id TEXT,
            sequence INTEGER NOT NULL CHECK (sequence > 0),
            event_name TEXT NOT NULL CHECK (
                event_name IN (
                    'process_started', 'suggestion_chunk',
                    'suggestion_reaction_committed', 'action_requested',
                    'action_resume_requested', 'action_summary',
                    'completion_chunk', 'process_paused',
                    'process_completed', 'error'
                )
            ),
            payload TEXT NOT NULL CHECK (json_valid(payload)),
            created_at TEXT NOT NULL,
            FOREIGN KEY (suggestion_id)
                REFERENCES agent_suggestions(suggestion_id) ON DELETE CASCADE,
            FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
            FOREIGN KEY (action_id) REFERENCES agent_actions(action_id) ON DELETE CASCADE,
            UNIQUE (suggestion_id, sequence)
        )
        """
    )
    columns = ", ".join(_PROCESS_EVENT_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO agent_process_events_v0082({columns})
        SELECT {columns}
        FROM agent_process_events
        ORDER BY event_id
        """
    )
    _replace_table(connection, "agent_process_events", "agent_process_events_v0082")


def _replace_table(
    connection: sqlite3.Connection, current_name: str, replacement_name: str
) -> None:
    connection.execute(f'DROP TABLE "{current_name}"')
    connection.execute(f'ALTER TABLE "{replacement_name}" RENAME TO "{current_name}"')


def _load_schema_objects(
    connection: sqlite3.Connection, table_name: str
) -> tuple[str, ...]:
    rows = connection.execute(
        """
        SELECT sql
        FROM sqlite_master
        WHERE tbl_name = ?
          AND type IN ('index', 'trigger')
          AND sql IS NOT NULL
        ORDER BY type, name
        """,
        (table_name,),
    ).fetchall()
    return tuple(str(row[0]) for row in rows)


def _restore_schema_objects(
    connection: sqlite3.Connection, statements: tuple[str, ...]
) -> None:
    for statement in statements:
        connection.execute(statement)


def _placeholders(values: tuple[str, ...]) -> str:
    return ",".join("?" for _ in values)


__all__ = ["apply_action_creation_cutover_migration"]
