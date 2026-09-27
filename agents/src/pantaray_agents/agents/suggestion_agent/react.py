from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Literal, Protocol

from pantaray_agents.agents.artifact_react import (
    NativeReactCompletion,
    NativeReactRunInput,
    ReactLoopPolicy,
    ReactLoopStep,
    ReactToolResult,
    resolve_react_tool_definitions,
    run_native_react,
)
from pantaray_agents.agents.artifact_react.transcript import (
    build_prompt_with_transcript,
)
from pantaray_agents.agents.core.mixins.llm_tool_use_mixin import LlmToolCallTurn
from pantaray_agents.schema.agent.action_message import (
    ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS,
)
from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.agent.suggestion import (
    SuggestionExtraction,
    SuggestionStructuredOutput,
)
from pantaray_llm.contracts.tool_use import (
    LlmToolContinuation,
    LlmToolDefinition,
    LlmToolResult,
)

from .research import SuggestionResearchTools

SUGGESTION_MAX_LLM_TURNS = 30
SUGGESTION_MAX_RESEARCH_TOOL_CALLS = 30
SUBMIT_SUGGESTION_TOOL_NAME = "submit_suggestion"
SUGGESTION_TOOL_IDS: tuple[str, ...] = (
    "memory_search",
    "get_memory_reference",
    "read",
    "list",
    "glob",
    "grep",
    "web_search",
    "web_extract",
)

type SuggestionStepRecorder = Callable[[ReactLoopStep], Awaitable[None]]
type SuggestionThoughtDiscarder = Callable[[], str | None]


class SuggestionToolCallGenerator(Protocol):
    async def __call__(
        self,
        *,
        prompt: str,
        tools: tuple[LlmToolDefinition, ...],
        continuation_mode: Literal["disabled", "stateless"],
        continuation: LlmToolContinuation | None,
        tool_result: LlmToolResult | None,
        system_instruction: str,
        stage: str,
    ) -> LlmToolCallTurn: ...


class SuggestionOutputParser(Protocol):
    def __call__(
        self,
        *,
        raw_text: str,
        parsed_output: SuggestionStructuredOutput | None,
    ) -> SuggestionExtraction: ...


def _terminal_tool() -> LlmToolDefinition:
    return LlmToolDefinition(
        name=SUBMIT_SUGGESTION_TOOL_NAME,
        description=(
            "Submit the final evidence-grounded intervention decision. This may be "
            "called on the first turn when the initial context is already sufficient."
        ),
        parameters={
            "type": "object",
            "additionalProperties": False,
            "required": [
                "has_suggestion",
                "answer",
                "interaction_contract",
                "suggestion_summary",
                "target_context",
            ],
            "properties": {
                "has_suggestion": {"type": "boolean"},
                "answer": {
                    "type": "string",
                    "maxLength": ACTION_MESSAGE_CONTENT_MAX_CODEPOINTS,
                },
                "interaction_contract": {
                    "type": ["string", "null"],
                    "enum": ["action_offer", "message_only", None],
                },
                "suggestion_summary": {"type": ["string", "null"]},
                "target_context": {
                    "oneOf": [
                        {"type": "null"},
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "required": ["organization_name", "project_name"],
                            "properties": {
                                "organization_name": {"type": ["string", "null"]},
                                "project_name": {"type": ["string", "null"]},
                            },
                        },
                    ]
                },
            },
        },
    )


async def run_suggestion_react(
    *,
    user_id: str,
    suggestion_id: str,
    initial_prompt: str,
    system_instruction: str,
    research_tools: SuggestionResearchTools,
    generate_tool_call: SuggestionToolCallGenerator,
    parse_output: SuggestionOutputParser,
    record_step: SuggestionStepRecorder,
    discard_llm_thoughts: SuggestionThoughtDiscarder,
) -> SuggestionExtraction:
    tool_definitions = resolve_react_tool_definitions(
        definitions=research_tools.build_tool_definitions(
            user_id=user_id,
            run_id=suggestion_id,
        ),
        tool_ids=SUGGESTION_TOOL_IDS,
    )

    async def call_llm(
        prompt: str,
        tools: tuple[LlmToolDefinition, ...],
        continuation: LlmToolContinuation | None,
        tool_result: LlmToolResult | None,
    ) -> LlmToolCallTurn:
        return await generate_tool_call(
            prompt=prompt,
            tools=tools,
            continuation_mode="stateless",
            continuation=continuation,
            tool_result=tool_result,
            system_instruction=system_instruction,
            stage="suggestion",
        )

    async def persist_step(step: ReactLoopStep) -> None:
        await record_step(step)

    async def project_tool_result(result: ReactToolResult) -> ReactToolResult:
        return result

    def complete(
        arguments: dict[str, JSONValue],
        _final_turn: bool,
    ) -> NativeReactCompletion[SuggestionExtraction]:
        raw_text = json.dumps(arguments, ensure_ascii=False, separators=(",", ":"))
        try:
            parsed = SuggestionStructuredOutput.model_validate(arguments)
            extraction = parse_output(raw_text=raw_text, parsed_output=parsed)
        except ValueError as exc:
            return NativeReactCompletion(
                value=None,
                final_text=raw_text,
                error_message=f"submit_suggestion was rejected: {str(exc)[:1200]}",
            )
        extraction["thinking"] = None
        extraction["prompt_text"] = initial_prompt
        extraction["response_text"] = raw_text
        return NativeReactCompletion(value=extraction, final_text=raw_text)

    def discard_thoughts() -> None:
        discard_llm_thoughts()

    result = await run_native_react(
        NativeReactRunInput(
            run_id=suggestion_id,
            tool_definitions=tool_definitions,
            terminal_tool=_terminal_tool(),
            complete=complete,
            build_prompt=lambda tool_results, last_error: build_prompt_with_transcript(
                initial_prompt=initial_prompt,
                tool_results=tool_results,
                last_error=last_error,
            ),
            call_llm=call_llm,
            record_step=persist_step,
            project_tool_result=project_tool_result,
            policy=ReactLoopPolicy(
                max_llm_turns=SUGGESTION_MAX_LLM_TURNS,
                max_tool_calls=SUGGESTION_MAX_RESEARCH_TOOL_CALLS,
            ),
            consume_llm_thoughts=discard_thoughts,
            final_turn_prompt=(
                "Research is now closed. Call submit_suggestion with the best "
                "evidence-grounded decision. If evidence is insufficient or the "
                "hard gates are not met, submit has_suggestion=false."
            ),
        )
    )
    if result.loop_result.status != "success" or result.value is None:
        raise RuntimeError(
            result.loop_result.last_error or "Suggestion ReAct loop failed"
        )
    return result.value


__all__ = [
    "SUBMIT_SUGGESTION_TOOL_NAME",
    "SUGGESTION_TOOL_IDS",
    "SUGGESTION_MAX_LLM_TURNS",
    "SUGGESTION_MAX_RESEARCH_TOOL_CALLS",
    "run_suggestion_react",
]
