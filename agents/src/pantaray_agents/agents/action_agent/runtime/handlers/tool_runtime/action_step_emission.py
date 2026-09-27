"""Project tool and assistant step notifications onto the existing Action events."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable

from pantaray_agents.application.action.ports import (
    ActionAssistantMessageEmission,
    ActionStepEmission,
)
from pantaray_agents.local_runtime.action_conversation.tool_subject import (
    project_tool_subject,
)
from pantaray_agents.schema.action_conversation import (
    ActionAssistantMessageEventData,
    ActionStepEventData,
    ActionStepEventPayload,
    visible_action_tool_id_from_step_name,
)


async def emit_visible_action_step(
    emit_action_step: Callable[[ActionStepEventPayload], Awaitable[None]],
    *,
    action_id: str,
    process_id: str,
    event: ActionStepEmission,
) -> None:
    """Emit a persisted assistant change or a visible tool replacement."""

    if isinstance(event, ActionAssistantMessageEmission):
        await emit_action_step(
            ActionAssistantMessageEventData(
                action_id=action_id,
                process_id=process_id,
                step_kind="assistant",
                step_id=event.step_id,
                step_number=event.step_number,
                status="success",
            )
        )
        return
    tool_id = visible_action_tool_id_from_step_name(event.step_name)
    if tool_id is None:
        return
    await emit_action_step(
        ActionStepEventData(
            action_id=action_id,
            process_id=process_id,
            step_kind="tool",
            step_id=event.step_id,
            step_number=event.step_number,
            tool_id=tool_id,
            label=event.label.strip(),
            subject=project_tool_subject(tool_id, json.dumps(event.tool_args)),
            status=event.status,
            started_at=event.started_at,
            completed_at=event.completed_at,
        )
    )


__all__ = ["emit_visible_action_step"]
