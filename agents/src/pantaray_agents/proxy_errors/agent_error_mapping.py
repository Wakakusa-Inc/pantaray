from __future__ import annotations

import re

from pantaray_agents.schema.agent.base import AgentError, ErrorType, JSONValue
from pantaray_llm.errors.error_contract import (
    PROXY_INSUFFICIENT_BALANCE,
    PROXY_LLM_TOOL_CALL_INVALID,
    PROXY_WALLET_CHECK_FAILED,
    ProxyErrorDetails,
    build_proxy_agent_error,
)
from pantaray_llm.errors.exceptions import LlmProxyExecutionError

_URL_RE = re.compile(r"https?://[^\s'\"<>]+", re.IGNORECASE)


def _sanitize_proxy_error_message(message: str) -> str:
    if not isinstance(message, str) or not message:
        return ""
    return _URL_RE.sub("<redacted_url>", message)


def _json_error_details(details: ProxyErrorDetails) -> dict[str, JSONValue]:
    serialized: dict[str, JSONValue] = {}
    for key, value in details.items():
        if value is None or isinstance(value, str | bool | int | float):
            serialized[key] = value
            continue
        raise TypeError(f"proxy error detail is not JSON scalar: {key}")
    return serialized


def build_llm_proxy_agent_error(
    *,
    exception: LlmProxyExecutionError,
    error_code_prefix: str,
) -> AgentError:
    sanitized_error_message = _sanitize_proxy_error_message(exception.error_message)
    proxy_payload = build_proxy_agent_error(
        surface_id="llm",
        error_code=exception.error_code,
        local_job_id=exception.local_job_id,
        upstream_provider=exception.upstream_provider,
        upstream_request_id=exception.upstream_request_id,
        upstream_status_code=exception.upstream_status_code,
        upstream_code=exception.upstream_code,
        profile_id=exception.profile_id,
        tool_call_violation_reason=exception.tool_call_violation_reason,
        actual_tool_call_count=exception.actual_tool_call_count,
        tool_name=exception.tool_name,
        response_status=exception.response_status,
        argument_path=exception.argument_path,
        schema_keyword=exception.schema_keyword,
        recovery=exception.recovery,
        suggested_action=exception.suggested_action,
    )
    error_details = _json_error_details(proxy_payload["error_details"])
    error_details["proxy_error_code"] = exception.error_code

    if exception.error_code == PROXY_INSUFFICIENT_BALANCE:
        return AgentError(
            error_type=ErrorType.VALIDATION_ERROR.value,
            error_code=f"{error_code_prefix}_INSUFFICIENT_BALANCE",
            error_message=sanitized_error_message,
            error_details=error_details,
            severity=proxy_payload["severity"],
            metadata=None,
        )

    if exception.error_code == PROXY_WALLET_CHECK_FAILED:
        return AgentError(
            error_type=ErrorType.INTERNAL_ERROR.value,
            error_code=f"{error_code_prefix}_WALLET_CHECK_FAILED",
            error_message=sanitized_error_message,
            error_details=error_details,
            severity=proxy_payload["severity"],
            metadata=None,
        )

    if exception.error_code == PROXY_LLM_TOOL_CALL_INVALID:
        return AgentError(
            error_type=ErrorType.LLM_API_ERROR.value,
            error_code=f"{error_code_prefix}_TOOL_CALL_INVALID",
            error_message=sanitized_error_message,
            error_details=error_details,
            severity=proxy_payload["severity"],
            metadata=None,
        )

    return AgentError(
        error_type=ErrorType.LLM_API_ERROR.value,
        error_code=f"{error_code_prefix}_LLM_RESPONSE_ERROR",
        error_message=sanitized_error_message,
        error_details=error_details,
        severity=proxy_payload["severity"],
        metadata=None,
    )


__all__ = ["build_llm_proxy_agent_error"]
