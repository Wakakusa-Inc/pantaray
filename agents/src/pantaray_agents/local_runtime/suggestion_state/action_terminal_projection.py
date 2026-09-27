from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.action_status import (
    ACTION_STATUS_CANCELED,
    ACTION_STATUS_ERROR,
    ACTION_STATUS_SUCCESS,
    ActionTerminalStatus,
    FinalizeActionTerminalCommand,
)
from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
    append_public_process_event,
)
from pantaray_agents.local_runtime.suggestion_state.public_projection import (
    EVENT_PROCESS_COMPLETED,
    rebuild_history_projection,
)
from pantaray_agents.local_runtime.suggestion_state.shared import serialize_json

PROCESS_STATUS_COMPLETED = "completed"
PROCESS_STATUS_FAILED = "failed"
PROCESS_STATUS_CANCELED = "canceled"


@dataclass(frozen=True)
class ActionTerminalProjectionResult:
    process_completed_sequence: int
    action_status: ActionTerminalStatus
    action_failure_code: str | None
    final_output: str | None
    failure_stage: str | None
    failure_message_public: str | None


def map_action_status_to_process_status(action_status: ActionTerminalStatus) -> str:
    if action_status == ACTION_STATUS_SUCCESS:
        return PROCESS_STATUS_COMPLETED
    if action_status == ACTION_STATUS_CANCELED:
        return PROCESS_STATUS_CANCELED
    if action_status == ACTION_STATUS_ERROR:
        return PROCESS_STATUS_FAILED
    raise ValueError(
        f"Unsupported action terminal status for process mapping: {action_status}"
    )


def finalize_action_terminal_projection(
    *,
    connection: sqlite3.Connection,
    command: FinalizeActionTerminalCommand,
) -> ActionTerminalProjectionResult:
    error_json = None
    if command.error_payload is not None:
        error_json = serialize_json(dict(command.error_payload))
    elif command.failure_code is not None:
        error_json = serialize_json(
            {
                "error_code": command.failure_code,
                "error_type": "runtime_error",
                "error_message": command.failure_message_public,
                "severity": "error",
            }
        )

    existing_action_row = connection.execute(
        """
        SELECT
            user_id,
            suggestion_id,
            prompt_name,
            prompt_version
        FROM agent_actions
        WHERE action_id = ?
        """,
        (command.action_id,),
    ).fetchone()
    if existing_action_row is None:
        raise RuntimeError("Action not found")
    if str(existing_action_row["user_id"]) != command.user_id:
        raise RuntimeError("Action owner mismatch")
    stored_suggestion_id = existing_action_row["suggestion_id"]
    normalized_stored_suggestion_id = (
        str(stored_suggestion_id) if stored_suggestion_id is not None else None
    )
    if normalized_stored_suggestion_id != command.suggestion_id:
        raise RuntimeError("Action suggestion provenance mismatch")
    resolved_prompt_name = command.prompt_name
    if resolved_prompt_name is None and existing_action_row is not None:
        resolved_prompt_name = str(existing_action_row["prompt_name"])
    resolved_prompt_version = command.prompt_version
    if resolved_prompt_version is None and existing_action_row is not None:
        resolved_prompt_version = str(existing_action_row["prompt_version"])
    if resolved_prompt_name is None or resolved_prompt_version is None:
        raise RuntimeError("action prompt metadata is missing for terminal projection")

    total_steps = command.total_steps or 0
    total_llm_steps = command.total_llm_steps or 0
    total_tool_steps = command.total_tool_steps or 0
    total_prompt_tokens = command.total_prompt_tokens or 0
    total_completion_tokens = command.total_completion_tokens or 0

    if command.suggestion_id is not None:
        cursor = connection.execute(
            """
            UPDATE agent_suggestions
            SET accepted_at = ?,
                action_command_id = ?,
                action_process_id = ?,
                action_status = ?,
                action_failure_code = ?,
                action_failure_stage = ?,
                action_failure_message_public = ?,
                action_request_payload = NULL,
                updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?)
            WHERE user_id = ? AND suggestion_id = ?
            """,
            (
                command.accepted_at,
                command.command_id,
                command.process_id,
                command.action_status,
                command.failure_code,
                command.failure_stage,
                command.failure_message_public,
                command.completed_at,
                command.user_id,
                command.suggestion_id,
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Suggestion not found")

    cursor = connection.execute(
        """
        UPDATE agent_actions
        SET status = ?,
            final_output = ?,
            error = ?,
            final_prompt_text = ?,
            total_steps = ?,
            total_llm_steps = ?,
            total_tool_steps = ?,
            total_prompt_tokens = ?,
            total_completion_tokens = ?,
            total_tokens = ?,
            prompt_name = ?,
            prompt_version = ?,
            updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', ?)
        WHERE action_id = ? AND user_id = ? AND status = 'processing'
        """,
        (
            command.action_status,
            command.final_output or "",
            error_json,
            command.final_prompt_text,
            total_steps,
            total_llm_steps,
            total_tool_steps,
            total_prompt_tokens,
            total_completion_tokens,
            total_prompt_tokens + total_completion_tokens,
            resolved_prompt_name,
            resolved_prompt_version,
            command.completed_at,
            command.action_id,
            command.user_id,
        ),
    )
    if cursor.rowcount != 1:
        raise RuntimeError("Action is not processing")
    stream_end_sequence = append_public_process_event(
        connection=connection,
        event_id=command.process_completed_event_id,
        suggestion_id=command.suggestion_id,
        user_id=command.user_id,
        action_id=command.action_id,
        event_name=EVENT_PROCESS_COMPLETED,
        payload=command.process_completed_payload,
        created_at=command.completed_at,
    )
    if command.suggestion_id is not None:
        rebuild_history_projection(
            connection=connection,
            user_id=command.user_id,
            suggestion_id=command.suggestion_id,
        )
    return ActionTerminalProjectionResult(
        process_completed_sequence=stream_end_sequence,
        action_status=command.action_status,
        action_failure_code=command.failure_code,
        final_output=command.final_output,
        failure_stage=command.failure_stage,
        failure_message_public=command.failure_message_public,
    )


__all__ = [
    "ActionTerminalProjectionResult",
    "finalize_action_terminal_projection",
    "map_action_status_to_process_status",
]
