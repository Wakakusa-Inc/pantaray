"""LLM ステップ共通のヘルパー。"""

from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    ActionPhase,
)
from pantaray_agents.agents.action_agent.runtime.state.context import (
    require_context as _require_context,
)
from pantaray_agents.agents.action_agent.runtime.steps.counters import (
    increment_llm_steps_taken,
)
from pantaray_agents.schema.agent.action import StepType

from .. import common


def _apply_llm_step_state_update(state: ActionAgentState, *, decided_at: str) -> None:
    """LLM ステップのカウンタと更新時刻を反映する。"""
    increment_llm_steps_taken(state)
    state["updated_at"] = decided_at


def _infer_supervisor_think_short_step_id(
    state: ActionAgentState,
    *,
    scope_handle: str,
    phase: ActionPhase,
) -> tuple[int, str]:
    """Infer a Supervisor THINK short ID for either lifecycle phase.

    During ToolValidationError repair, reuse the local number of the preceding
    THINK entry from the same history stage.
    """
    context = _require_context(state)
    streak = int(context.get("tool_validation_error_streak", 0) or 0)
    local_step_number: int | None = None
    if streak > 0:
        history_list = common.get_history_for_scope(state, scope_handle)
        for entry in reversed(history_list):
            if entry.get("phase") != phase:
                continue
            if entry.get("step_type") != StepType.LLM_OUTPUT:
                continue
            prev_short_step_id = entry.get("short_step_id")
            if isinstance(prev_short_step_id, str) and prev_short_step_id:
                try:
                    parsed = common.parse_short_step_id(prev_short_step_id)
                    local_step_number = parsed.local_step_number
                except ValueError:
                    local_step_number = None
            break

    if local_step_number is None:
        local_step_number = common.get_or_increment_local_step_number(
            state, scope_handle
        )
    short_step_id = common.build_short_step_id(
        scope_handle, local_step_number, StepType.LLM_OUTPUT
    )
    return local_step_number, short_step_id


__all__ = [
    "_apply_llm_step_state_update",
    "_infer_supervisor_think_short_step_id",
]
