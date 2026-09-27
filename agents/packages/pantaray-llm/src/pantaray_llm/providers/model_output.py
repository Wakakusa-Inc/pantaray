from __future__ import annotations

from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.request import LlmModelOutputError
from pantaray_llm.errors import (
    PROXY_LLM_TOOL_CALL_INVALID,
    ProviderError,
    ToolCallViolationReason,
    coerce_tool_call_violation_reason,
)

_STOP_REASONS = frozenset[ToolCallViolationReason]({"response_blocked"})


def model_output_error_from_proxy_error(
    error: ProviderError,
) -> LlmModelOutputError | None:
    if error.code != PROXY_LLM_TOOL_CALL_INVALID:
        return None
    details = error.details or {}
    reason = coerce_tool_call_violation_reason(
        details.get("tool_call_violation_reason")
    )
    if reason is None:
        raise AssertionError("tool-call contract error must include a violation reason")
    return LlmModelOutputError(
        code=PROXY_LLM_TOOL_CALL_INVALID,
        message=error.message,
        recovery="stop" if reason in _STOP_REASONS else "repair_next_turn",
        violation_reason=reason,
        actual_tool_call_count=_read_int(details, "actual_tool_call_count"),
        tool_name=_read_str(details, "tool_name"),
        response_status=_read_str(details, "response_status"),
        argument_path=_read_str(details, "argument_path"),
        schema_keyword=_read_str(details, "schema_keyword"),
    )


def _read_str(details: dict[str, JSONValue], key: str) -> str | None:
    value = details.get(key)
    return value if isinstance(value, str) and value else None


def _read_int(details: dict[str, JSONValue], key: str) -> int | None:
    value = details.get(key)
    return value if isinstance(value, int) else None


__all__ = ["model_output_error_from_proxy_error"]
