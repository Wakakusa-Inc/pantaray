"""ユーザー入力を Action の正式な履歴ステップとして記録する。"""

from __future__ import annotations

import copy
from collections.abc import Sequence

from pantaray_agents.agents.action_agent.runtime.handlers.nodes import common
from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    ActionPhase,
    HistoryEntry,
)
from pantaray_agents.agents.action_agent.runtime.tool_attachments import (
    ToolAttachment,
)
from pantaray_agents.schema.agent.action import StepType


def has_persisted_user_request_step(
    state: ActionAgentState,
    *,
    step_id: str,
) -> bool:
    return any(
        entry.get("step_id") == step_id
        for entries in state.get("history_by_scope", {}).values()
        for entry in entries
    )


def project_persisted_user_request_step(
    state: ActionAgentState,
    *,
    step_id: str,
    step_number: int,
    local_step_number: int,
    short_step_id: str,
    request_text: str,
    occurred_at: str,
    history_phase: ActionPhase,
    attachments: Sequence[ToolAttachment] = (),
) -> ActionAgentState:
    """Project an already-durable USER step into runtime state without writing DB."""

    if not request_text.strip():
        raise ValueError("request_text must be a non-empty string")
    if not occurred_at.strip():
        raise ValueError("occurred_at must be a non-empty string")
    if step_number < 1 or local_step_number < 1:
        raise ValueError("USER step numbers must be positive")

    updated_state = copy.deepcopy(state)
    scope_handle = common.SUPERVISOR_SCOPE_HANDLE
    expected_local_step_number = common.get_or_increment_local_step_number(
        updated_state,
        scope_handle,
    )
    if expected_local_step_number != local_step_number:
        raise ValueError("persisted USER local_step_number is not the next value")
    expected_short_step_id = common.build_short_step_id(
        scope_handle,
        local_step_number,
        StepType.USER_REQUEST,
    )
    if short_step_id != expected_short_step_id:
        raise ValueError("persisted USER short_step_id is inconsistent")
    history_entry: HistoryEntry = {
        "step_id": step_id,
        "step_number": step_number,
        "phase": history_phase,
        "step_type": StepType.USER_REQUEST,
        "summary": "",
        "user_request_text": request_text,
        "tool_id": None,
        "started_at": occurred_at,
        "completed_at": occurred_at,
        "short_step_id": short_step_id,
    }
    if attachments:
        history_entry["attachments"] = list(attachments)
    common.append_history_entry(
        updated_state,
        scope_handle=scope_handle,
        entry=history_entry,
    )
    updated_state["step"] = step_number + 1
    updated_state["updated_at"] = occurred_at
    return updated_state


__all__ = ["has_persisted_user_request_step", "project_persisted_user_request_step"]
