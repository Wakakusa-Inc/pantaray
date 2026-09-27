from __future__ import annotations

from pantaray_llm.errors import (
    PROXY_LLM_TOOL_CALL_INVALID,
    LlmProxyExecutionError,
)


def build_tool_call_repair_feedback(
    exc: LlmProxyExecutionError, *, max_tool_calls: int = 1
) -> str:
    """Tell the model how to redo an invalid tool-call turn.

    ``max_tool_calls`` is how many calls the turn may carry: single-call agents
    keep the default, the Action Supervisor passes the batch limit of the turn.
    """

    if exc.error_code != PROXY_LLM_TOOL_CALL_INVALID:
        raise ValueError("repair feedback requires a tool-call contract error")
    reason = exc.tool_call_violation_reason or "invalid_response"
    detail = exc.error_message.strip() or "The previous tool call was invalid."
    expectation = (
        "Return exactly one provided tool call"
        if max_tool_calls <= 1
        else f"Return between 1 and {max_tool_calls} provided tool calls, each"
    )
    return (
        "The previous response violated the tool-call contract.\n"
        f"- reason: {reason}\n"
        f"- detail: {detail}\n"
        f"{expectation} with arguments matching its schema."
    )


__all__ = [
    "build_tool_call_repair_feedback",
]
