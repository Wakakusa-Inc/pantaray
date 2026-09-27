"""Action runtime resume route decisions."""

from __future__ import annotations

from typing import Literal

from pantaray_agents.action_status import ACTION_FAILURE_CODE_RESUME_NOT_ALLOWED
from pantaray_agents.agents.action_agent.runtime.models.tool_call import (
    NextActionModel,
    ToolCallModel,
)
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
from pantaray_agents.agents.action_agent.runtime.state.context import (
    get_context_view,
)
from pantaray_agents.agents.action_agent.support.status import ACTION_TERMINAL_STATUSES

from .resume_errors import ResumeStateError
from .retired_orchestration import has_retired_goal_worker_mode

type ResumeRouteName = Literal[
    "init",
    "think",
    "action",
    "finalize",
    "halt",
]


def graph_route_from_execution_think_state(state: ActionAgentState) -> str:
    if state.get("run_authority") == "superseded" or state.get("skip_persist"):
        return "finalize"
    if state.get("status") in ACTION_TERMINAL_STATUSES or state.get("final_output"):
        return "finalize"

    tool = _next_action_tool(state)
    if isinstance(tool, ToolCallModel):
        return "action"
    return "think"


def graph_route_from_resume_state(state: ActionAgentState) -> ResumeRouteName:
    if state.get("run_authority") == "superseded" or state.get("skip_persist"):
        return "finalize"
    if state.get("status") in ACTION_TERMINAL_STATUSES or state.get("final_output"):
        return "finalize"

    if has_retired_goal_worker_mode(get_context_view(state)):
        raise ResumeStateError(
            failure_code=ACTION_FAILURE_CODE_RESUME_NOT_ALLOWED,
            message="Goal Worker checkpoints cannot resume in the parent-only graph.",
        )

    if state.get("pending_approval_request") is not None:
        return "halt"

    normalized_phase = str(state.get("phase") or "").strip().lower()
    if normalized_phase == "planning":
        raise ResumeStateError(
            failure_code=ACTION_FAILURE_CODE_RESUME_NOT_ALLOWED,
            message="Planning checkpoints cannot resume in the parent-only graph.",
        )
    tool = _next_action_tool(state)
    if isinstance(tool, ToolCallModel):
        if normalized_phase != "executing":
            raise ResumeStateError(
                failure_code=ACTION_FAILURE_CODE_RESUME_NOT_ALLOWED,
                message=(
                    "Pending Supervisor tool requires the executing phase; "
                    f"got {state.get('phase')!r}."
                ),
            )
        return "action"

    if normalized_phase == "init":
        return "init"
    if normalized_phase == "executing":
        return "think"
    if normalized_phase == "finalizing":
        return "finalize"
    raise ResumeStateError(
        failure_code=ACTION_FAILURE_CODE_RESUME_NOT_ALLOWED,
        message=f"Unsupported action resume phase: {state.get('phase')!r}",
    )


def _next_action_tool(state: ActionAgentState) -> ToolCallModel | None:
    next_action = state.get("next_action")
    if next_action is None:
        return None
    if not isinstance(next_action, NextActionModel):
        raise ValueError(
            "Action runtime invariant violated: next_action must be NextActionModel."
        )
    return next_action.tool
