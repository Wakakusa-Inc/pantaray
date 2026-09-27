from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Literal, TypeGuard, cast

from pydantic import TypeAdapter

from pantaray_agents.local_runtime.llm_proxy.types import LocalLlmProxyResultMeta
from pantaray_llm.contracts.action_turn import LlmActionTurnResponse
from pantaray_llm.contracts.conversation import LlmProviderTurn
from pantaray_llm.contracts.tool_use import LlmToolUseResponse
from pantaray_llm.errors import LLM_PROVIDERS, LlmProvider

TEXT_OUTPUT_BLOCK_TYPE = "output_text"
OUTPUT_ROLE = "assistant"
_NATIVE_RESPONSE_ADAPTER: TypeAdapter[LlmToolUseResponse | LlmActionTurnResponse] = (
    TypeAdapter(LlmToolUseResponse | LlmActionTurnResponse)
)
_PROVIDER_TURN_ADAPTER: TypeAdapter[LlmProviderTurn] = TypeAdapter(LlmProviderTurn)
type ProxyOutcome = Literal["complete", "no_results", "partial_results"]
type ProxySuggestedAction = Literal[
    "refine_query",
    "change_url",
    "narrow_scope",
    "retry_later",
    "switch_tool",
    "abort",
    "adjust_input",
]


def is_mapping(value: object) -> TypeGuard[Mapping[str, object]]:
    return isinstance(value, Mapping)


def coerce_non_empty_string(value: object, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise RuntimeError(f"{field_name} must be a string")
    normalized = value.strip()
    if not normalized:
        raise RuntimeError(f"{field_name} must not be empty")
    return normalized


def extract_text(payload: Mapping[str, object]) -> str:
    output = payload.get("output")
    if not isinstance(output, list):
        raise RuntimeError("LLM proxy response missing output")
    parts: list[str] = []
    for message in output:
        if not is_mapping(message):
            raise RuntimeError("LLM proxy response output message is invalid")
        role = coerce_non_empty_string(message.get("role"), field_name="output.role")
        if role != OUTPUT_ROLE:
            raise RuntimeError("LLM proxy response role must be assistant")
        content = message.get("content")
        if not isinstance(content, list):
            raise RuntimeError("LLM proxy response content is invalid")
        for block in content:
            if not is_mapping(block):
                raise RuntimeError("LLM proxy response block is invalid")
            block_type = coerce_non_empty_string(
                block.get("type"), field_name="output.content.type"
            )
            if block_type == TEXT_OUTPUT_BLOCK_TYPE:
                parts.append(
                    coerce_non_empty_string(
                        block.get("text"), field_name="output.content.text"
                    )
                )
    return "".join(parts)


def extract_usage(payload: Mapping[str, object]) -> dict[str, int] | None:
    usage = payload.get("usage")
    if not is_mapping(usage):
        return None
    return _extract_usage_values(usage, field_name="usage")


def extract_error_usage(
    details: Mapping[str, object] | None,
) -> dict[str, int] | None:
    if details is None:
        return None
    usage_keys = {
        "prompt_tokens",
        "cached_prompt_tokens",
        "cache_write_prompt_tokens",
        "completion_tokens",
        "total_tokens",
    }
    if usage_keys.isdisjoint(details):
        return None
    return _extract_usage_values(details, field_name="error.details")


def _extract_usage_values(
    usage: Mapping[str, object],
    *,
    field_name: str,
) -> dict[str, int]:
    required_values = {
        key: usage.get(key)
        for key in ("prompt_tokens", "completion_tokens", "total_tokens")
    }
    if any(
        not isinstance(value, int) or isinstance(value, bool)
        for value in required_values.values()
    ):
        raise RuntimeError(f"LLM proxy response {field_name} is invalid")
    values = cast(dict[str, int], required_values)
    for key in (
        "cached_prompt_tokens",
        "cache_write_prompt_tokens",
        "reasoning_tokens",
    ):
        value = usage.get(key)
        if value is None:
            continue
        if not isinstance(value, int) or isinstance(value, bool):
            raise RuntimeError(f"LLM proxy response {field_name} is invalid")
        values[key] = value
    return values


def read_optional_string(
    payload: Mapping[str, object] | None,
    field_name: str,
) -> str | None:
    if payload is None:
        return None
    value = payload.get(field_name)
    return value if isinstance(value, str) and value.strip() else None


def read_optional_int(
    payload: Mapping[str, object] | None,
    field_name: str,
) -> int | None:
    if payload is None:
        return None
    value = payload.get(field_name)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def read_llm_provider(payload: Mapping[str, object] | None) -> LlmProvider | None:
    provider = read_optional_string(payload, "upstream_provider")
    if provider is None or provider not in LLM_PROVIDERS:
        return None
    return cast(LlmProvider, provider)


def extract_meta(payload: Mapping[str, object]) -> LocalLlmProxyResultMeta | None:
    meta = payload.get("meta")
    if not is_mapping(meta):
        return None
    local_job_id = read_optional_string(meta, "local_job_id")
    upstream_provider = read_llm_provider(meta)
    profile_id = read_optional_string(meta, "profile_id")
    outcome = read_optional_string(meta, "outcome")
    if (
        local_job_id is None
        or upstream_provider is None
        or profile_id is None
        or outcome not in {"complete", "no_results", "partial_results"}
    ):
        raise RuntimeError("LLM proxy response meta is invalid")
    payload_meta: LocalLlmProxyResultMeta = {
        "local_job_id": local_job_id,
        "upstream_provider": upstream_provider,
        "profile_id": profile_id,
        "outcome": cast(ProxyOutcome, outcome),
    }
    upstream_request_id = read_optional_string(meta, "upstream_request_id")
    if upstream_request_id is not None:
        payload_meta["upstream_request_id"] = upstream_request_id
    suggested_action = read_optional_string(meta, "suggested_action")
    if suggested_action in {
        "refine_query",
        "change_url",
        "narrow_scope",
        "retry_later",
        "switch_tool",
        "abort",
        "adjust_input",
    }:
        payload_meta["suggested_action"] = cast(ProxySuggestedAction, suggested_action)
    return payload_meta


def extract_thinking(payload: Mapping[str, object]) -> str | None:
    thinking = payload.get("thinking")
    return thinking if isinstance(thinking, str) and thinking.strip() else None


def extract_tool_use(
    payload: Mapping[str, object],
) -> LlmToolUseResponse | LlmActionTurnResponse | None:
    raw_tool_use = payload.get("tool_use")
    if raw_tool_use is None:
        return None
    return _NATIVE_RESPONSE_ADAPTER.validate_python(raw_tool_use)


def extract_provider_turn(payload: Mapping[str, object]) -> LlmProviderTurn | None:
    """The Action turn's own output items, sent at the top level of a response.

    Only a request that sent a conversation is handed one, so this is absent on
    every other request and on a cloud deployment that predates the field.
    """

    raw_provider_turn = payload.get("provider_turn")
    if raw_provider_turn is None:
        return None
    return _PROVIDER_TURN_ADAPTER.validate_python(raw_provider_turn)


def parse_response_text(*, text: str, response_schema: object | None) -> object | None:
    """Decode the delivered answer with the caller's own response type.

    The caller's type never crosses the wire, so both routes decode the text
    they received here. Text that is not the JSON the caller asked for stays
    undecoded, and the caller's own contract check reports it.
    """

    if response_schema is None:
        return None
    try:
        loaded = json.loads(text)
    except (TypeError, json.JSONDecodeError):
        return None
    model_validate = getattr(response_schema, "model_validate", None)
    if callable(model_validate):
        return cast(object, model_validate(loaded))
    return cast(object, loaded)


__all__ = [
    "coerce_non_empty_string",
    "extract_meta",
    "extract_error_usage",
    "extract_provider_turn",
    "extract_text",
    "extract_thinking",
    "extract_tool_use",
    "extract_usage",
    "is_mapping",
    "parse_response_text",
    "read_llm_provider",
    "read_optional_int",
    "read_optional_string",
]
