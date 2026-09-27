from __future__ import annotations

import pytest

from pantaray_agents.agents.core.tool_call_repair import (
    build_tool_call_repair_feedback,
)
from pantaray_llm.errors import (
    PROXY_LLM_TOOL_CALL_INVALID,
    LlmProxyExecutionError,
)


def _invalid_call_error() -> LlmProxyExecutionError:
    return LlmProxyExecutionError(
        error_code=PROXY_LLM_TOOL_CALL_INVALID,
        error_message="arguments did not match the schema",
        recovery="repair_next_turn",
        retryable=False,
    )


def test_single_call_agents_are_told_to_return_exactly_one_call() -> None:
    feedback = build_tool_call_repair_feedback(_invalid_call_error())

    assert "Return exactly one provided tool call" in feedback


@pytest.mark.parametrize("limit", [2, 3])
def test_batch_turns_are_told_their_call_limit(limit: int) -> None:
    feedback = build_tool_call_repair_feedback(
        _invalid_call_error(), max_tool_calls=limit
    )

    assert f"Return between 1 and {limit} provided tool calls" in feedback
    assert "exactly one" not in feedback
