"""Pure projection of canonical Action terminal authority."""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

from pantaray_agents.action_status import (
    ActionTerminalStatus,
)
from pantaray_agents.local_runtime.runtime.action_logical_run_authority import (
    ActionLogicalRunAuthority,
    parse_action_run_terminal_command,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.action_conversation import (
    ActionConversationSummary,
    PublicActionError,
)

from .repository import ActionConversationIntegrityError


@dataclass(frozen=True, slots=True)
class ActionRunTerminalProjection:
    status: ActionTerminalStatus
    completed_at: str
    final_output: str | None
    error: PublicActionError | None


def project_action_run_terminal(
    *,
    user_id: str,
    action: ActionConversationSummary,
    authority: ActionLogicalRunAuthority,
) -> ActionRunTerminalProjection:
    """Validate one canonical ``stream_end`` and expose only its public outcome."""

    try:
        command = parse_action_run_terminal_command(
            user_id=user_id,
            action_id=action.action_id,
            suggestion_id=action.suggestion_id,
            authority=authority,
        )
    except MigrationError as exc:
        raise ActionConversationIntegrityError(str(exc)) from exc
    public_error = (
        None
        if command.action_status == "success"
        else PublicActionError(
            code=cast(str, command.failure_code),
            message=cast(str, command.failure_message_public),
        )
    )
    return ActionRunTerminalProjection(
        status=command.action_status,
        # The validated stored timestamp keeps its precision in the public view.
        completed_at=cast(str, authority.completed_at),
        final_output=command.final_output,
        error=public_error,
    )


__all__ = ["ActionRunTerminalProjection", "project_action_run_terminal"]
