from __future__ import annotations

import sqlite3

from .action_history_schema import (
    create_agent_action_steps_table,
    create_agent_actions_table,
    create_agent_suggestions_table,
    ensure_agent_action_steps_indexes,
    ensure_agent_actions_indexes,
    ensure_agent_suggestions_indexes,
    is_agent_action_steps_aligned,
    is_agent_actions_aligned,
    is_agent_suggestions_aligned,
)
from .connection import column_exists

LEGACY_SUGGESTIONS_TABLE = "agent_suggestions_legacy_v7"
LEGACY_ACTIONS_TABLE = "agent_actions_legacy_v7"
LEGACY_ACTION_STEPS_TABLE = "agent_action_steps_legacy_v7"
LEGACY_PROMPT_NAME = "legacy/local_runtime"
LEGACY_PROMPT_VERSION = "pre-v7"
LEGACY_SUGGESTION_PROMPT_TEXT = "[legacy local runtime prompt unavailable]"
DEFAULT_ACTION_STATUS = "success"
DEFAULT_GENERATION = "1"
DEFAULT_COUNT = "0"


def apply_local_action_state_migration(connection: sqlite3.Connection) -> None:
    migrate_suggestions = not is_agent_suggestions_aligned(connection)
    migrate_actions = not is_agent_actions_aligned(connection)
    migrate_action_steps = not is_agent_action_steps_aligned(connection)

    if not (migrate_suggestions or migrate_actions or migrate_action_steps):
        ensure_agent_suggestions_indexes(connection)
        ensure_agent_actions_indexes(connection)
        ensure_agent_action_steps_indexes(connection)
        return

    connection.execute("PRAGMA defer_foreign_keys = ON;")
    if migrate_suggestions:
        connection.execute(
            f"ALTER TABLE agent_suggestions RENAME TO {LEGACY_SUGGESTIONS_TABLE}"
        )
        create_agent_suggestions_table(connection)
    if migrate_actions:
        connection.execute(
            f"ALTER TABLE agent_actions RENAME TO {LEGACY_ACTIONS_TABLE}"
        )
        create_agent_actions_table(connection)
    if migrate_action_steps:
        connection.execute(
            f"ALTER TABLE agent_action_steps RENAME TO {LEGACY_ACTION_STEPS_TABLE}"
        )
        create_agent_action_steps_table(connection)

    if migrate_suggestions:
        _copy_agent_suggestions(connection)
    if migrate_actions:
        _copy_agent_actions(connection)
    if migrate_action_steps:
        _copy_agent_action_steps(connection)

    if migrate_action_steps:
        connection.execute(f"DROP TABLE {LEGACY_ACTION_STEPS_TABLE}")
    if migrate_actions:
        connection.execute(f"DROP TABLE {LEGACY_ACTIONS_TABLE}")
    if migrate_suggestions:
        connection.execute(f"DROP TABLE {LEGACY_SUGGESTIONS_TABLE}")

    ensure_agent_suggestions_indexes(connection)
    ensure_agent_actions_indexes(connection)
    ensure_agent_action_steps_indexes(connection)


def _copy_agent_suggestions(connection: sqlite3.Connection) -> None:
    error_expr = _first_existing_column_expr(
        connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        column_names=("error", "error_json"),
    )
    prompt_name_expr = _non_processing_string_expr(
        connection=connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        column_name="prompt_name",
        fallback=LEGACY_PROMPT_NAME,
    )
    prompt_version_expr = _non_processing_string_expr(
        connection=connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        column_name="prompt_version",
        fallback=LEGACY_PROMPT_VERSION,
    )
    prompt_text_expr = _non_processing_string_expr(
        connection=connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        column_name="prompt_text",
        fallback=LEGACY_SUGGESTION_PROMPT_TEXT,
    )
    response_text_expr = _non_processing_string_expr(
        connection=connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        column_name="response_text",
        fallback_column="answer",
    )
    has_suggestion_expr = _agent_suggestion_has_suggestion_expr(connection)
    interaction_contract_expr = _conditional_nullable_expr(
        connection=connection,
        table_name=LEGACY_SUGGESTIONS_TABLE,
        condition_expr=f"{has_suggestion_expr} = 1",
        column_name="interaction_contract",
    )
    connection.execute(
        f"""
        INSERT INTO agent_suggestions(
            suggestion_id,
            user_id,
            status,
            answer,
            thinking,
            error,
            prompt_text,
            response_text,
            prompt_name,
            prompt_version,
            has_suggestion,
            request_images_count,
            used_images_count,
            interaction_contract,
            user_reaction,
            accepted_at,
            rejected_at,
            action_status,
            action_failure_code,
            action_failure_stage,
            action_failure_message_public,
            action_request_payload,
            action_process_id,
            action_execution_id,
            action_command_id,
            action_started_at,
            process_event_sequence,
            created_at,
            updated_at
        )
        SELECT
            suggestion_id,
            user_id,
            status,
            answer,
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "thinking")},
            {error_expr},
            {prompt_text_expr},
            {response_text_expr},
            {prompt_name_expr},
            {prompt_version_expr},
            {has_suggestion_expr},
            {_integer_default_expr(connection, LEGACY_SUGGESTIONS_TABLE, "request_images_count")},
            {_integer_default_expr(connection, LEGACY_SUGGESTIONS_TABLE, "used_images_count")},
            {interaction_contract_expr},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "user_reaction")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "accepted_at")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "rejected_at")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_status")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_failure_code")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_failure_stage")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_failure_message_public")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_request_payload")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_process_id")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_execution_id")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_command_id")},
            {_optional_column_expr(connection, LEGACY_SUGGESTIONS_TABLE, "action_started_at")},
            {_integer_default_expr(connection, LEGACY_SUGGESTIONS_TABLE, "process_event_sequence")},
            created_at,
            updated_at
        FROM {LEGACY_SUGGESTIONS_TABLE}
        """
    )


def _copy_agent_actions(connection: sqlite3.Connection) -> None:
    connection.execute(
        f"""
        INSERT INTO agent_actions(
            action_id,
            user_id,
            suggestion_id,
            status,
            final_output,
            error,
            final_prompt_text,
            generation,
            steps_budget,
            llm_steps_budget,
            tool_steps_budget,
            token_budget,
            total_steps,
            total_llm_steps,
            total_tool_steps,
            total_prompt_tokens,
            total_completion_tokens,
            total_tokens,
            prompt_name,
            prompt_version,
            created_at,
            updated_at
        )
        SELECT
            action_id,
            user_id,
            suggestion_id,
            status,
            COALESCE(final_output, ''),
            {_first_existing_column_expr(connection, LEGACY_ACTIONS_TABLE, ("error", "error_json"))},
            {_optional_column_expr(connection, LEGACY_ACTIONS_TABLE, "final_prompt_text")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "generation", default=DEFAULT_GENERATION)},
            {_optional_column_expr(connection, LEGACY_ACTIONS_TABLE, "steps_budget")},
            {_optional_column_expr(connection, LEGACY_ACTIONS_TABLE, "llm_steps_budget")},
            {_optional_column_expr(connection, LEGACY_ACTIONS_TABLE, "tool_steps_budget")},
            {_optional_column_expr(connection, LEGACY_ACTIONS_TABLE, "token_budget")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_steps")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_llm_steps")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_tool_steps")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_prompt_tokens")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_completion_tokens")},
            {_integer_default_expr(connection, LEGACY_ACTIONS_TABLE, "total_tokens")},
            {_string_default_expr(connection, LEGACY_ACTIONS_TABLE, "prompt_name", LEGACY_PROMPT_NAME)},
            {_string_default_expr(connection, LEGACY_ACTIONS_TABLE, "prompt_version", LEGACY_PROMPT_VERSION)},
            created_at,
            updated_at
        FROM {LEGACY_ACTIONS_TABLE}
        """
    )


def _copy_agent_action_steps(connection: sqlite3.Connection) -> None:
    local_step_expr = _optional_column_expr(
        connection, LEGACY_ACTION_STEPS_TABLE, "local_step_number"
    )
    step_number_expr = _first_existing_column_expr(
        connection,
        LEGACY_ACTION_STEPS_TABLE,
        ("step_number", "local_step_number"),
        default="1",
    )
    short_step_expr = _step_short_id_expr(connection)
    step_type_expr = _normalized_step_type_expr(connection)
    step_name_expr = _step_name_expr(connection)
    connection.execute(
        f"""
        INSERT INTO agent_action_steps(
            step_id,
            action_id,
            user_id,
            parent_step_id,
            step_number,
            local_step_number,
            short_step_id,
            step_type,
            step_name,
            status,
            goal_handle,
            requirement_handle,
            parallel_group_id,
            parallel_depth,
            parallel_index,
            retry_count,
            started_at,
            completed_at,
            execution_time_ms,
            prompt_tokens,
            completion_tokens,
            user_request_text,
            thinking,
            llm_prompt_text,
            llm_response_text,
            tool_args,
            tool_output,
            runtime_state_checkpoint,
            runtime_state_checkpoint_version,
            error,
            created_at
        )
        SELECT
            {_first_existing_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, ("step_id", "action_step_id"))},
            action_id,
            user_id,
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "parent_step_id")},
            {step_number_expr},
            {local_step_expr},
            {short_step_expr},
            {step_type_expr},
            {step_name_expr},
            {_string_default_expr(connection, LEGACY_ACTION_STEPS_TABLE, "status", DEFAULT_ACTION_STATUS)},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "goal_handle")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "requirement_handle")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "parallel_group_id")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "parallel_depth")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "parallel_index")},
            {_integer_default_expr(connection, LEGACY_ACTION_STEPS_TABLE, "retry_count")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "started_at")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "completed_at")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "execution_time_ms")},
            {_integer_default_expr(connection, LEGACY_ACTION_STEPS_TABLE, "prompt_tokens")},
            {_integer_default_expr(connection, LEGACY_ACTION_STEPS_TABLE, "completion_tokens")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "user_request_text")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "thinking")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "llm_prompt_text")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "llm_response_text")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "tool_args")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "tool_output")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "runtime_state_checkpoint")},
            {_optional_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, "runtime_state_checkpoint_version")},
            {_first_existing_column_expr(connection, LEGACY_ACTION_STEPS_TABLE, ("error",), default="NULL")},
            created_at
        FROM {LEGACY_ACTION_STEPS_TABLE}
        """
    )


def _optional_column_expr(
    connection: sqlite3.Connection, table_name: str, column_name: str
) -> str:
    if column_exists(connection, table_name=table_name, column_name=column_name):
        return column_name
    return "NULL"


def _first_existing_column_expr(
    connection: sqlite3.Connection,
    table_name: str,
    column_names: tuple[str, ...],
    *,
    default: str = "NULL",
) -> str:
    for column_name in column_names:
        if column_exists(connection, table_name=table_name, column_name=column_name):
            return column_name
    return default


def _string_default_expr(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    fallback: str,
) -> str:
    if column_exists(connection, table_name=table_name, column_name=column_name):
        return f"COALESCE({column_name}, '{fallback}')"
    return f"'{fallback}'"


def _non_processing_string_expr(
    *,
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    fallback: str | None = None,
    fallback_column: str | None = None,
) -> str:
    if column_exists(connection, table_name=table_name, column_name=column_name):
        base_expr = column_name
    elif fallback_column is not None and column_exists(
        connection, table_name=table_name, column_name=fallback_column
    ):
        base_expr = f"COALESCE({fallback_column}, '')"
    elif fallback is not None:
        base_expr = f"'{fallback}'"
    else:
        base_expr = "NULL"
    return f"CASE WHEN status = 'processing' THEN NULL ELSE {base_expr} END"


def _integer_default_expr(
    connection: sqlite3.Connection,
    table_name: str,
    column_name: str,
    *,
    default: str = DEFAULT_COUNT,
) -> str:
    if column_exists(connection, table_name=table_name, column_name=column_name):
        return f"COALESCE({column_name}, {default})"
    return default


def _conditional_nullable_expr(
    *,
    connection: sqlite3.Connection,
    table_name: str,
    condition_expr: str,
    column_name: str,
) -> str:
    column_expr = _optional_column_expr(connection, table_name, column_name)
    return f"CASE WHEN {condition_expr} THEN {column_expr} ELSE NULL END"


def _agent_suggestion_has_suggestion_expr(connection: sqlite3.Connection) -> str:
    if column_exists(
        connection, table_name=LEGACY_SUGGESTIONS_TABLE, column_name="has_suggestion"
    ):
        return (
            "CASE "
            "WHEN status = 'processing' THEN NULL "
            "WHEN interaction_contract IS NOT NULL THEN 1 "
            "ELSE 0 END"
        )
    return "CASE WHEN status = 'processing' THEN NULL ELSE 0 END"


def _normalized_step_type_expr(connection: sqlite3.Connection) -> str:
    if not column_exists(
        connection, table_name=LEGACY_ACTION_STEPS_TABLE, column_name="step_type"
    ):
        return "'llm_output'"
    return (
        "CASE "
        "WHEN step_type = 'user_request' THEN 'user_request' "
        "WHEN step_type = 'tool_execution' THEN 'tool_execution' "
        "WHEN step_type = 'llm_output' THEN 'llm_output' "
        "ELSE 'llm_output' END"
    )


def _step_name_expr(connection: sqlite3.Connection) -> str:
    if column_exists(
        connection, table_name=LEGACY_ACTION_STEPS_TABLE, column_name="step_name"
    ):
        return "COALESCE(step_name, 'legacy step')"
    if column_exists(
        connection, table_name=LEGACY_ACTION_STEPS_TABLE, column_name="step_type"
    ):
        return "COALESCE(step_type, 'legacy step')"
    return "'legacy step'"


def _step_short_id_expr(connection: sqlite3.Connection) -> str:
    if column_exists(
        connection, table_name=LEGACY_ACTION_STEPS_TABLE, column_name="short_step_id"
    ):
        return "short_step_id"
    if column_exists(
        connection,
        table_name=LEGACY_ACTION_STEPS_TABLE,
        column_name="local_step_number",
    ):
        return "('legacy-' || local_step_number || '-MIGRATED')"
    return "NULL"
