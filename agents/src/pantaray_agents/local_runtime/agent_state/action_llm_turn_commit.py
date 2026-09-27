"""Atomically adopt an Action LLM output and its immutable commentary rows."""

from __future__ import annotations

import sqlite3
from typing import cast

from pantaray_agents.schema.agent.action import StepType
from pantaray_agents.schema.agent.action_assistant_message import ActionLlmTurnCommit
from pantaray_agents.schema.agent.base import StepStatusType
from pantaray_agents.schema.repositories.repository import DBRow


class ActionLlmTurnCommitError(ValueError):
    """The response lost its owner or conflicts with an already adopted output."""


def save_action_llm_turn_in_connection(
    connection: sqlite3.Connection,
    *,
    payload: DBRow,
    turn: ActionLlmTurnCommit,
) -> None:
    """Write the output and utterances in save_action_step's transaction."""
    if (
        payload["step_type"] != StepType.LLM_OUTPUT
        or payload["step_name"] != "supervisor_think"
        or payload["status"] != StepStatusType.SUCCESS
        or payload["goal_handle"] != "S"
        or payload["runtime_state_checkpoint"] is None
    ):
        raise ActionLlmTurnCommitError(
            "Action turn adoption requires a successful Supervisor THINK checkpoint"
        )
    owner = connection.execute(
        """SELECT adopted.adopted_process_id, adopted.step_number
        FROM agent_action_steps AS adopted
        JOIN agent_actions AS action
          ON action.action_id = adopted.action_id AND action.user_id = adopted.user_id
        JOIN processes AS process
          ON process.process_id = adopted.adopted_process_id
         AND process.action_id = action.action_id AND process.user_id = action.user_id
        JOIN jobs AS job
          ON job.job_id = process.current_job_id AND job.process_id = process.process_id
         AND job.user_id = process.user_id
        WHERE adopted.step_id = :user_step_id
          AND adopted.user_id = :user_id AND adopted.action_id = :action_id
          AND adopted.step_type = 'user_request' AND adopted.status = 'success'
          AND action.status = 'processing'
          AND process.kind = 'action' AND process.status = 'running'
          AND job.job_type = 'execute_action' AND job.logical_key = :action_id
          AND job.status = 'running' AND job.cancel_requested_at IS NULL
          AND adopted.step_id = (
              SELECT step_id FROM agent_action_steps
              WHERE user_id = :user_id AND action_id = :action_id
                AND step_type = 'user_request' AND status = 'success'
                AND adopted_process_id IS NOT NULL AND step_number IS NOT NULL
              ORDER BY step_number DESC, step_id DESC LIMIT 1
          )""",
        {
            "user_step_id": turn.user_step_id,
            "user_id": payload["user_id"],
            "action_id": payload["action_id"],
        },
    ).fetchone()
    if owner is None:
        raise ActionLlmTurnCommitError("Action turn USER owner is no longer active")

    think_step_number = cast(int, payload["step_number"])
    if think_step_number <= owner["step_number"]:
        raise ActionLlmTurnCommitError("Action THINK must follow its adopted USER")
    inserted = _insert_immutable_step(connection, payload)
    if not inserted:
        stored_message_ids = tuple(
            row["step_id"]
            for row in connection.execute(
                """SELECT step_id FROM agent_action_steps
                WHERE user_id = ? AND action_id = ? AND parent_step_id = ?
                  AND step_type = 'assistant_message'
                ORDER BY step_number, step_id""",
                (payload["user_id"], payload["action_id"], payload["step_id"]),
            )
        )
        if stored_message_ids != tuple(message.step_id for message in turn.messages):
            raise ActionLlmTurnCommitError(
                "adopted Action commentary cannot be replaced"
            )
    previous_step_number = owner["step_number"]
    for message in turn.messages:
        if not previous_step_number < message.step_number < think_step_number:
            raise ActionLlmTurnCommitError(
                "commentary must follow its USER and precede its THINK in source order"
            )
        previous_step_number = message.step_number
        _insert_immutable_step(
            connection,
            {
                "step_id": message.step_id,
                "action_id": payload["action_id"],
                "user_id": payload["user_id"],
                "parent_step_id": payload["step_id"],
                "step_number": message.step_number,
                "local_step_number": message.local_step_number,
                "short_step_id": message.short_step_id,
                "step_type": StepType.ASSISTANT_MESSAGE,
                "step_name": "assistant_commentary",
                "status": StepStatusType.SUCCESS,
                "goal_handle": "S",
                "llm_response_text": message.content,
                "adopted_process_id": owner["adopted_process_id"],
                "started_at": message.created_at,
                "completed_at": message.created_at,
                "created_at": message.created_at,
            },
        )


def _insert_immutable_step(connection: sqlite3.Connection, payload: DBRow) -> bool:
    # Column names come from ActionStepRecord or the fixed assistant projection.
    columns = tuple(payload)
    existing = connection.execute(
        f"SELECT {', '.join(columns)} FROM agent_action_steps WHERE step_id = ?",
        (payload["step_id"],),
    ).fetchone()
    if existing is not None:
        # The repository clock changes on retries; the first commit owns created_at.
        if any(
            existing[column] != payload[column]
            for column in columns
            if column != "created_at"
        ):
            raise ActionLlmTurnCommitError(
                "Action step identity is already bound to different content"
            )
        return False
    placeholders = ", ".join("?" for _ in columns)
    connection.execute(
        f"INSERT INTO agent_action_steps ({', '.join(columns)}) VALUES ({placeholders})",
        tuple(payload[column] for column in columns),
    )
    return True
