from __future__ import annotations

from pantaray_agents.agents.artifact_react import run_artifact_update_react_loop
from pantaray_agents.agents.artifact_react.types import ReactLoopResult
from pantaray_agents.schema.agent import AgentRequest, AgentResponse

from .types import (
    ReActAgentDefinition,
    ReActAgentRunResult,
)


class ReActAgentRunner:
    """Runs ReAct agents through a shared update flow."""

    async def run[RequestT: AgentRequest, ResponseT: AgentResponse](
        self,
        *,
        definition: ReActAgentDefinition[RequestT, ResponseT],
        request: RequestT,
    ) -> ResponseT:
        run_input = await definition.prepare(request)
        execution = await run_artifact_update_react_loop(
            run_id=run_input.run_id,
            base_text=run_input.base_text,
            build_prompt=run_input.build_prompt,
            call_llm=run_input.call_llm,
            apply_patch=run_input.apply_patch,
            commit_patch=run_input.commit_patch,
            record_step=run_input.record_step,
            logical_path=run_input.logical_path,
            policy=run_input.policy,
            tools=run_input.tools,
            consume_llm_thoughts=run_input.consume_llm_thoughts,
        )
        result = ReActAgentRunResult(
            final_text=execution.final_text,
            loop_result=execution.loop_result,
        )
        if execution.loop_result.status != "success":
            error = definition.error_from_loop_result(execution.loop_result)
            return await run_input.build_error_response(request, error)
        if (
            run_input.commit_completed_without_patch is not None
            and not _has_successful_tool_step(execution.loop_result)
        ):
            await run_input.commit_completed_without_patch(run_input.base_text)
        return await run_input.build_success_response(request, result)


def _has_successful_tool_step(loop_result: ReactLoopResult) -> bool:
    return any(
        step.step_kind == "tool" and step.status == "success"
        for step in loop_result.steps
    )
