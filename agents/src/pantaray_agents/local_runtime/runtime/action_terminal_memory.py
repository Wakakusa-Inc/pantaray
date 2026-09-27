"""Publication side of an Action terminal.

A successful Action publishes one canonical memory revision. Every terminal —
success, error or cancel — binds the completed USER turn that the Memory agent
later reads as evidence; only a successful turn has a published revision to
reference. Both run inside the terminal transaction owned by
``action_terminal_repository``.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.action_status import FinalizeActionTerminalCommand
from pantaray_agents.local_runtime.memory_catalog.checkpoint import (
    deserialize_memory_draft,
)
from pantaray_agents.local_runtime.memory_catalog.models import MemoryRevision
from pantaray_agents.local_runtime.memory_catalog.publication import (
    MemoryPublicationRequest,
    publish_inline_revision,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.agent.action import MemoryDraftCheckpointModel


class InvalidActionMemoryDraftError(RuntimeError):
    """A successful Action cannot publish its canonical memory revision."""


@dataclass(frozen=True, slots=True)
class CompletedActionTurnBinding:
    source_action_revision_id: str | None
    turn_start_step_number: int
    turn_end_step_number: int
    action_prompt_name: str
    action_prompt_version: str


def publish_action_memory_in_connection(
    *, connection: sqlite3.Connection, command: FinalizeActionTerminalCommand
) -> MemoryRevision:
    if command.memory_draft_json is None:
        raise InvalidActionMemoryDraftError(
            "successful Action terminalization requires memory_draft_json"
        )
    try:
        model = MemoryDraftCheckpointModel.model_validate_json(
            command.memory_draft_json
        )
    except ValueError as exc:
        raise InvalidActionMemoryDraftError(
            "Action memory draft checkpoint is invalid"
        ) from exc
    draft = deserialize_memory_draft(model)
    if draft.user_id != command.user_id or len(draft.documents) != 1:
        raise InvalidActionMemoryDraftError(
            "Action memory draft does not match the terminal command"
        )
    if draft.documents[0].content.strip() != str(command.final_output or "").strip():
        raise InvalidActionMemoryDraftError(
            "Action memory draft body differs from final_output"
        )
    return publish_inline_revision(
        connection=connection,
        request=MemoryPublicationRequest(
            source="action",
            source_record_id=command.action_id,
            draft=draft,
            body_kind="inline",
        ),
    )


def load_completed_action_turn_binding_in_connection(
    *,
    connection: sqlite3.Connection,
    command: FinalizeActionTerminalCommand,
    action_revision: MemoryRevision | None,
) -> CompletedActionTurnBinding | None:
    """The turn this terminal completed, or ``None`` when it has no history.

    An Action can reach an error or cancel terminal before its USER step is
    durable. That terminal completed no turn, so it binds nothing. Assistant
    messages preceding this USER belong to its evidence, without crossing
    an earlier USER or a different logical run.
    """

    start_rows = connection.execute(
        """
        SELECT COALESCE((
            SELECT MIN(assistant.step_number) FROM agent_action_steps AS assistant
            WHERE assistant.user_id=current_user.user_id
              AND assistant.action_id=current_user.action_id
              AND assistant.step_type='assistant_message'
              AND assistant.adopted_process_id=current_user.adopted_process_id
              AND assistant.step_number<current_user.step_number
              AND assistant.step_number>COALESCE((
                  SELECT MAX(previous_user.step_number) FROM agent_action_steps AS previous_user
                  WHERE previous_user.user_id=current_user.user_id
                    AND previous_user.action_id=current_user.action_id
                    AND previous_user.step_type='user_request'
                    AND previous_user.step_number<current_user.step_number
              ),0)
        ),current_user.step_number) AS step_number
        FROM agent_action_steps AS current_user
        WHERE current_user.user_id = ? AND current_user.action_id = ?
          AND current_user.step_type = 'user_request' AND current_user.status = 'success'
          AND current_user.user_message_id = ?
        """,
        (command.user_id, command.action_id, command.command_id),
    ).fetchall()
    if len(start_rows) > 1:
        raise MigrationError("completed Action turn start USER step is not unique")
    if not start_rows:
        return None
    turn_start = int(start_rows[0]["step_number"])
    end_row = connection.execute(
        """
        SELECT MAX(step_number) AS turn_end_step_number
        FROM agent_action_steps
        WHERE user_id = ? AND action_id = ?
        """,
        (command.user_id, command.action_id),
    ).fetchone()
    action_row = connection.execute(
        """
        SELECT prompt_name, prompt_version
        FROM agent_actions
        WHERE user_id = ? AND action_id = ?
        """,
        (command.user_id, command.action_id),
    ).fetchone()
    if end_row is None or end_row["turn_end_step_number"] is None:
        raise MigrationError("completed Action turn end step is absent")
    turn_end = int(end_row["turn_end_step_number"])
    if turn_end < turn_start:
        raise MigrationError("completed Action turn step range is invalid")
    if action_row is None:
        raise MigrationError("completed Action prompt identity is absent")
    prompt_name = str(action_row["prompt_name"] or "").strip()
    prompt_version = str(action_row["prompt_version"] or "").strip()
    if not prompt_name or not prompt_version:
        raise MigrationError("completed Action prompt identity is invalid")
    return CompletedActionTurnBinding(
        source_action_revision_id=(
            None if action_revision is None else action_revision.revision_id
        ),
        turn_start_step_number=turn_start,
        turn_end_step_number=turn_end,
        action_prompt_name=prompt_name,
        action_prompt_version=prompt_version,
    )
