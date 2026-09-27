from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.schema.agent.base import JSONValue

from ..repository.executions import ToolInvocationTerminalStateError
from ..tool_result_finalization import (
    InvocationToolResultOwner,
    ToolResultFinalizationRequest,
    finalize_local_tool_result,
)

ACTION_CANCELED_TOOL_INVOCATION_ERROR_TYPE = "ActionCanceledToolInvocation"
ACTION_CANCELED_TOOL_INVOCATION_ERROR_MESSAGE = (
    "tool invocation was canceled because action execution was canceled"
)


@dataclass(frozen=True, slots=True)
class ToolInvocationCancelResult:
    invocation_id: str
    canceled: bool


def _build_action_canceled_output() -> dict[str, JSONValue]:
    return {
        "error": {
            "type": ACTION_CANCELED_TOOL_INVOCATION_ERROR_TYPE,
            "message": ACTION_CANCELED_TOOL_INVOCATION_ERROR_MESSAGE,
        }
    }


def cancel_inflight_tool_invocation(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    invocation_id: str,
    completed_at: str,
) -> ToolInvocationCancelResult:
    try:
        finalize_local_tool_result(
            db_path=db_path,
            busy_timeout_ms=busy_timeout_ms,
            request=ToolResultFinalizationRequest(
                owner=InvocationToolResultOwner(
                    invocation_id=invocation_id,
                    completed_at=completed_at,
                    status="canceled",
                    completion_scope="invocation",
                ),
                output=_build_action_canceled_output(),
            ),
        )
    except ToolInvocationTerminalStateError:
        return ToolInvocationCancelResult(
            invocation_id=invocation_id,
            canceled=False,
        )
    return ToolInvocationCancelResult(invocation_id=invocation_id, canceled=True)


__all__ = [
    "ACTION_CANCELED_TOOL_INVOCATION_ERROR_MESSAGE",
    "ACTION_CANCELED_TOOL_INVOCATION_ERROR_TYPE",
    "ToolInvocationCancelResult",
    "cancel_inflight_tool_invocation",
]
