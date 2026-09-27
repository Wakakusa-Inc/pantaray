"""Action-owned construction of finalized formal tool-step results."""

from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
from pantaray_agents.agents.action_agent.runtime.steps.tool import (
    FinalizedToolStepResult,
    ToolStepStatus,
    build_finalized_tool_step,
)
from pantaray_agents.local_runtime.tooling.tool_result_finalization import (
    FinalizedToolOutput,
)
from pantaray_agents.schema.agent.base import AgentError
from pantaray_agents.schema.tool_result import UnprojectedToolOutput

from .finalization_boundary import finalize_action_step_output
from .shared import FailedToolControl, ToolExecutionResult


def finalized_execution_step(
    result: ToolExecutionResult,
    *,
    status: ToolStepStatus | None = None,
    error: AgentError | None = None,
) -> FinalizedToolStepResult:
    return build_finalized_tool_step(
        status=status or result.status,
        output=result.finalized_output,
        error=error,
    )


def finalize_synthetic_step(
    state: ActionAgentState,
    *,
    step_id: str,
    status: ToolStepStatus,
    output: UnprojectedToolOutput,
    error: AgentError,
) -> FinalizedToolStepResult:
    manifest_id = _required_state_id(state, "manifest_id")
    action_id = _required_state_id(state, "action_id")
    user_id = _required_state_id(state, "user_id")
    finalized = finalize_action_step_output(
        manifest_id=manifest_id,
        action_id=action_id,
        user_id=user_id,
        step_id=step_id,
        output=output,
    )
    return build_finalized_tool_step(status=status, output=finalized, error=error)


def finalize_error_step(
    state: ActionAgentState,
    *,
    step_id: str,
    finalized_output: FinalizedToolOutput | None,
    raw_output: UnprojectedToolOutput,
    error: AgentError,
) -> FinalizedToolStepResult:
    if finalized_output is not None:
        return build_finalized_tool_step(
            status="error",
            output=finalized_output,
            error=error,
        )
    return finalize_synthetic_step(
        state,
        step_id=step_id,
        status="error",
        output=raw_output,
        error=error,
    )


def failed_result_error(
    control: FailedToolControl,
    *,
    error_code: str,
) -> AgentError:
    return AgentError(
        error_type=control.failure.error_type,
        error_code=error_code,
        error_message=control.failure.message,
        severity="warning",
    )


def _required_state_id(state: ActionAgentState, key: str) -> str:
    value = state.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"formal tool step requires state.{key}")
    return value


__all__ = [
    "failed_result_error",
    "finalize_error_step",
    "finalize_synthetic_step",
    "finalized_execution_step",
]
