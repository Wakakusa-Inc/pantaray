from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pantaray_agents.local_runtime.llm_proxy.response_parsing import (
    extract_usage,
    is_mapping,
    read_llm_provider,
    read_optional_int,
    read_optional_string,
)
from pantaray_llm.contracts.action_turn import LlmActionTurnResponse
from pantaray_llm.contracts.tool_use import LlmToolUseResponse
from pantaray_llm.errors import (
    PROXY_INVALID_UPSTREAM_RESPONSE,
    PROXY_LLM_TOOL_CALL_INVALID,
    LlmProxyExecutionError,
    LlmRecoveryStrategy,
    coerce_tool_call_violation_reason,
)


def build_invalid_tool_response_error(
    *,
    message: str,
    request_json: Mapping[str, object],
    response_payload: Mapping[str, object],
) -> LlmProxyExecutionError:
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if is_mapping(metadata) else None
    response_meta = response_payload.get("meta")
    response_meta_mapping = response_meta if is_mapping(response_meta) else None
    return LlmProxyExecutionError(
        error_code=PROXY_LLM_TOOL_CALL_INVALID,
        error_message=message,
        retryable=False,
        recovery="stop",
        local_job_id=read_optional_string(metadata_mapping, "local_job_id"),
        upstream_provider=read_llm_provider(response_meta_mapping),
        upstream_request_id=read_optional_string(
            response_meta_mapping, "upstream_request_id"
        ),
        profile_id=read_optional_string(request_json, "inference_profile"),
        usage_metadata=extract_usage(response_payload),
        tool_call_violation_reason="invalid_response",
    )


def parse_model_output_error(
    *,
    request_json: Mapping[str, object],
    response_payload: Mapping[str, object],
) -> LlmProxyExecutionError | None:
    raw_error = response_payload.get("model_error")
    if raw_error is None:
        return None
    if not is_mapping(raw_error):
        raise _invalid_model_error(
            request_json=request_json,
            response_payload=response_payload,
            message="LLM proxy returned an invalid model_error object.",
        )
    raw_message = raw_error.get("message")
    raw_recovery = raw_error.get("recovery")
    reason = coerce_tool_call_violation_reason(raw_error.get("violation_reason"))
    if (
        raw_error.get("code") != PROXY_LLM_TOOL_CALL_INVALID
        or not isinstance(raw_message, str)
        or not raw_message.strip()
        or raw_recovery not in {"repair_next_turn", "stop"}
        or reason is None
    ):
        raise _invalid_model_error(
            request_json=request_json,
            response_payload=response_payload,
            message="LLM proxy returned an incomplete model_error contract.",
        )
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if is_mapping(metadata) else None
    response_meta = response_payload.get("meta")
    response_meta_mapping = response_meta if is_mapping(response_meta) else None
    return LlmProxyExecutionError(
        error_code=PROXY_LLM_TOOL_CALL_INVALID,
        error_message=raw_message,
        retryable=False,
        recovery=cast(LlmRecoveryStrategy, raw_recovery),
        local_job_id=read_optional_string(metadata_mapping, "local_job_id"),
        upstream_provider=read_llm_provider(response_meta_mapping),
        upstream_request_id=read_optional_string(
            response_meta_mapping, "upstream_request_id"
        ),
        profile_id=read_optional_string(request_json, "inference_profile"),
        usage_metadata=extract_usage(response_payload),
        tool_call_violation_reason=reason,
        actual_tool_call_count=read_optional_int(raw_error, "actual_tool_call_count"),
        tool_name=read_optional_string(raw_error, "tool_name"),
        response_status=read_optional_string(raw_error, "response_status"),
        argument_path=read_optional_string(raw_error, "argument_path"),
        schema_keyword=read_optional_string(raw_error, "schema_keyword"),
    )


def _invalid_model_error(
    *,
    request_json: Mapping[str, object],
    response_payload: Mapping[str, object],
    message: str,
) -> LlmProxyExecutionError:
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if is_mapping(metadata) else None
    return LlmProxyExecutionError(
        error_code=PROXY_INVALID_UPSTREAM_RESPONSE,
        error_message=message,
        retryable=True,
        recovery="retry_same_request",
        local_job_id=read_optional_string(metadata_mapping, "local_job_id"),
        profile_id=read_optional_string(request_json, "inference_profile"),
        usage_metadata=extract_usage(response_payload),
        upstream_status_code=200,
        upstream_code="invalid_model_error",
    )


def build_invalid_success_response_error(
    *,
    message: str,
    request_json: Mapping[str, object],
    response_payload: Mapping[str, object],
    usage_metadata: dict[str, int] | None,
) -> LlmProxyExecutionError:
    metadata = request_json.get("metadata")
    metadata_mapping = metadata if is_mapping(metadata) else None
    response_meta = response_payload.get("meta")
    response_meta_mapping = response_meta if is_mapping(response_meta) else None
    return LlmProxyExecutionError(
        error_code=PROXY_INVALID_UPSTREAM_RESPONSE,
        error_message=message,
        retryable=True,
        recovery="retry_same_request",
        local_job_id=read_optional_string(metadata_mapping, "local_job_id"),
        upstream_provider=read_llm_provider(response_meta_mapping),
        upstream_request_id=read_optional_string(
            response_meta_mapping,
            "upstream_request_id",
        ),
        profile_id=read_optional_string(request_json, "inference_profile"),
        upstream_status_code=200,
        upstream_code="invalid_success_response",
        usage_metadata=usage_metadata,
    )


def validate_tool_response_contract(
    *,
    request_json: Mapping[str, object],
    response_payload: Mapping[str, object],
    tool_use: LlmToolUseResponse | LlmActionTurnResponse | None,
) -> None:
    request_tool_use = request_json.get("tool_use")
    if not is_mapping(request_tool_use):
        if tool_use is not None:
            raise build_invalid_tool_response_error(
                message="LLM proxy returned an unexpected native tool response.",
                request_json=request_json,
                response_payload=response_payload,
            )
        return
    if tool_use is None:
        raise build_invalid_tool_response_error(
            message="LLM proxy returned no native tool call.",
            request_json=request_json,
            response_payload=response_payload,
        )
    requested_action_turn = request_tool_use.get("mode") == "action_turn"
    if requested_action_turn != isinstance(tool_use, LlmActionTurnResponse):
        raise build_invalid_tool_response_error(
            message="LLM proxy returned a different native response variant than requested.",
            request_json=request_json,
            response_payload=response_payload,
        )
    requested_max_calls = request_tool_use.get("max_parallel_tool_calls")
    if (
        not isinstance(requested_max_calls, int)
        or len(tool_use.calls) > requested_max_calls
    ):
        raise build_invalid_tool_response_error(
            message="LLM proxy returned more native tool calls than requested.",
            request_json=request_json,
            response_payload=response_payload,
        )
    if isinstance(tool_use, LlmActionTurnResponse):
        if response_payload.get("output") != []:
            raise build_invalid_tool_response_error(
                message="LLM proxy Action responses must keep messages in the Action turn.",
                request_json=request_json,
                response_payload=response_payload,
            )
        return
    continuation = tool_use.continuation
    continuation_mode = request_tool_use.get("continuation_mode")
    if continuation_mode == "stateless" and continuation is None:
        raise build_invalid_tool_response_error(
            message="LLM proxy omitted required native tool continuation state.",
            request_json=request_json,
            response_payload=response_payload,
        )
    if continuation_mode == "disabled" and continuation is not None:
        raise build_invalid_tool_response_error(
            message="LLM proxy returned unexpected native tool continuation state.",
            request_json=request_json,
            response_payload=response_payload,
        )


__all__ = [
    "build_invalid_success_response_error",
    "build_invalid_tool_response_error",
    "parse_model_output_error",
    "validate_tool_response_contract",
]
