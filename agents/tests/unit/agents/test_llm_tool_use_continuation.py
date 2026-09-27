from __future__ import annotations

from dataclasses import dataclass

import pytest

from pantaray_agents.agents.core.mixins.llm_tool_use_mixin import (
    LlmToolUseResponseError,
    _validate_tool_call_response,
)
from pantaray_llm.contracts.tool_use import (
    AnthropicToolContinuation,
    LlmToolCall,
    LlmToolContinuation,
    OpenAiToolContinuation,
)


@dataclass(frozen=True, slots=True)
class _Response:
    tool_calls: tuple[LlmToolCall, ...]
    tool_continuation: LlmToolContinuation | None


def _response(continuation: LlmToolContinuation | None) -> _Response:
    return _Response(
        tool_calls=(LlmToolCall(call_id="call-1", name="completed", arguments={}),),
        tool_continuation=continuation,
    )


@pytest.mark.parametrize(
    "continuation",
    [
        OpenAiToolContinuation(
            provider="openai",
            history_items=[
                {"role": "user", "content": [{"type": "input_text", "text": "prompt"}]}
            ],
        ),
        AnthropicToolContinuation(
            provider="anthropic",
            messages=[
                {"role": "user", "content": [{"type": "text", "text": "prompt"}]}
            ],
        ),
    ],
    ids=["openai", "anthropic"],
)
def test_a_stateless_turn_accepts_every_continuation_member(
    continuation: LlmToolContinuation,
) -> None:
    turn = _validate_tool_call_response(
        response=_response(continuation), continuation_mode="stateless"
    )

    assert turn.continuation is continuation


def test_a_stateless_turn_without_continuation_state_is_rejected() -> None:
    with pytest.raises(LlmToolUseResponseError):
        _validate_tool_call_response(
            response=_response(None), continuation_mode="stateless"
        )
