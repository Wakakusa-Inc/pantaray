"""web_search ツール実行の専用ランタイム。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NotRequired, Required, TypedDict

from pantaray_agents.agents.action_agent.runtime.handlers.web_tool_error_mapper import (
    map_web_tool_error,
)
from pantaray_agents.agents.action_agent.tools import ToolDefinition
from pantaray_agents.local_runtime.web_tools.client import (
    WebContentInvalidResponseError,
    build_web_tools_wrapper_context,
    invoke_web_tools_wrapper,
    require_non_empty_string,
)
from pantaray_agents.schema.agent.base import JSONValue
from pantaray_llm.errors import (
    PROXY_OUTCOME_COMPLETE,
    PROXY_OUTCOME_NO_RESULTS,
    PROXY_SUGGESTED_ACTION_REFINE_QUERY,
    ProxyAgentErrorPayload,
    ProxyToolResultMeta,
    build_proxy_tool_result_meta,
)
from pantaray_llm.profiles import (
    WEB_SEARCH_COUNTRIES,
    WEB_SEARCH_PROFILE_ID,
    WEB_SEARCH_TOPIC_GENERAL,
    WEB_SEARCH_TOPICS,
)

if TYPE_CHECKING:  # pragma: no cover
    from pantaray_agents.agents.action_agent import ActionAgent
    from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState


class _WebSearchResultRow(TypedDict, total=False):
    title: str
    url: str
    content: str
    score: object


class _WebSearchImageRow(TypedDict, total=False):
    url: str
    description: str


class _WebSearchResponse(TypedDict, total=False):
    status: object
    query: object
    results: list[_WebSearchResultRow]
    images: list[_WebSearchImageRow]
    upstream_request_id: str
    error: object


class WebSearchResult(TypedDict, total=False):
    title: Required[str]
    url: Required[str]
    content: Required[str]
    score: Required[float]


class WebSearchImage(TypedDict):
    url: str
    description: str


class WebSearchPayload(TypedDict, total=False):
    status: Required[str]
    query: Required[str]
    results: Required[list[WebSearchResult]]
    images: Required[list[WebSearchImage]]
    meta: NotRequired[ProxyToolResultMeta]
    error: NotRequired[ProxyAgentErrorPayload]


@dataclass(slots=True)
class WebSearchExecutionOutcome:
    status: str
    payload: WebSearchPayload
    prompt_tokens: int
    completion_tokens: int


def _coerce_result_row(value: object) -> _WebSearchResultRow | None:
    if not isinstance(value, dict):
        return None
    row: _WebSearchResultRow = {}
    if "title" in value:
        row["title"] = value.get("title")
    if "url" in value:
        row["url"] = value.get("url")
    if "content" in value:
        row["content"] = value.get("content")
    if "score" in value:
        row["score"] = value.get("score")
    return row


def _coerce_image_row(value: object) -> _WebSearchImageRow | None:
    if not isinstance(value, dict):
        return None
    return {
        "url": value.get("url"),
        "description": value.get("description"),
    }


def _coerce_search_response(value: object) -> _WebSearchResponse | None:
    if not isinstance(value, dict):
        return None
    results_value = value.get("results")
    images_value = value.get("images")
    if not isinstance(results_value, list):
        return None
    if not isinstance(images_value, list):
        return None

    results: list[_WebSearchResultRow] = []
    for row in results_value:
        typed_row = _coerce_result_row(row)
        if typed_row is None:
            return None
        results.append(typed_row)

    images: list[_WebSearchImageRow] = []
    for row in images_value:
        typed_row = _coerce_image_row(row)
        if typed_row is None:
            return None
        images.append(typed_row)

    response: _WebSearchResponse = {
        "status": value.get("status"),
        "query": value.get("query"),
        "results": results,
        "images": images,
    }
    meta_value = value.get("meta")
    if meta_value is not None:
        if not isinstance(meta_value, dict):
            return None
        upstream_request_id = meta_value.get("upstream_request_id")
        if upstream_request_id is not None:
            if (
                not isinstance(upstream_request_id, str)
                or not upstream_request_id.strip()
            ):
                return None
            response["upstream_request_id"] = upstream_request_id.strip()
    if "error" in value:
        response["error"] = value.get("error")
    return response


def _normalize_results(rows: list[_WebSearchResultRow]) -> list[WebSearchResult]:
    normalized: list[WebSearchResult] = []
    for row in rows:
        title = require_non_empty_string(row.get("title"), field_name="title")
        url = require_non_empty_string(row.get("url"), field_name="url")
        content = require_non_empty_string(row.get("content"), field_name="content")
        score = row.get("score")
        if not isinstance(score, int | float) or isinstance(score, bool):
            raise ValueError("score")
        normalized.append(
            {
                "title": title,
                "url": url,
                "content": content,
                "score": float(score),
            }
        )
    return normalized


def _normalize_images(rows: list[_WebSearchImageRow]) -> list[WebSearchImage]:
    normalized: list[WebSearchImage] = []
    for row in rows:
        normalized.append(
            {
                "url": require_non_empty_string(row.get("url"), field_name="url"),
                "description": require_non_empty_string(
                    row.get("description"),
                    field_name="description",
                ),
            }
        )
    return normalized


def _normalize_wrapper_payload(value: object) -> WebSearchPayload:
    response = _coerce_search_response(value)
    if response is None:
        raise ValueError("invalid_response")

    payload: WebSearchPayload = {
        "status": require_non_empty_string(response.get("status"), field_name="status"),
        "query": require_non_empty_string(response.get("query"), field_name="query"),
        "results": _normalize_results(response.get("results") or []),
        "images": _normalize_images(response.get("images") or []),
    }
    if "error" in response and response["error"] is not None:
        raise WebContentInvalidResponseError("error")
    return payload


def _build_search_meta(
    *,
    payload: WebSearchPayload,
    request_id: str,
    upstream_request_id: str | None,
) -> ProxyToolResultMeta:
    if payload["results"] or payload["images"]:
        return build_proxy_tool_result_meta(
            request_id=request_id,
            upstream_provider="tavily",
            profile_id=WEB_SEARCH_PROFILE_ID,
            outcome=PROXY_OUTCOME_COMPLETE,
            upstream_request_id=upstream_request_id,
        )
    return build_proxy_tool_result_meta(
        request_id=request_id,
        upstream_provider="tavily",
        profile_id=WEB_SEARCH_PROFILE_ID,
        outcome=PROXY_OUTCOME_NO_RESULTS,
        upstream_request_id=upstream_request_id,
        suggested_action=PROXY_SUGGESTED_ACTION_REFINE_QUERY,
    )


def _require_optional_search_enum(
    value: object,
    *,
    field_name: str,
    allowed_values: tuple[str, ...],
) -> str | None:
    if value is None:
        return None
    normalized = require_non_empty_string(value, field_name=field_name)
    if normalized not in allowed_values:
        raise ValueError(field_name)
    return normalized


async def run_web_search_tool(
    agent: ActionAgent,
    step_id: str,
    tool_def: ToolDefinition,
    args: dict[str, JSONValue],
    state: ActionAgentState,
) -> WebSearchExecutionOutcome:
    """web_search を実行し、cloud wrapper 由来の検索結果を返す。"""

    _ = agent

    query = require_non_empty_string(args.get("query"), field_name="query")
    topic = _require_optional_search_enum(
        args.get("topic"),
        field_name="topic",
        allowed_values=WEB_SEARCH_TOPICS,
    )
    country = _require_optional_search_enum(
        args.get("country"),
        field_name="country",
        allowed_values=WEB_SEARCH_COUNTRIES,
    )
    if country is not None and topic not in (None, WEB_SEARCH_TOPIC_GENERAL):
        raise ValueError("country")

    runtime_cfg = tool_def.runtime_config or {}
    max_retries = int(runtime_cfg.get("max_retries", 3) or 3)
    request_context = build_web_tools_wrapper_context(
        user_id=state.get("user_id"),
        action_id=state.get("action_id"),
    )
    wrapper_args: dict[str, JSONValue] = {"query": query}
    if topic is not None:
        wrapper_args["topic"] = topic
    if country is not None:
        wrapper_args["country"] = country

    try:
        wrapper_response = await invoke_web_tools_wrapper(
            tool_id="web_search",
            web_tool_profile=WEB_SEARCH_PROFILE_ID,
            args=wrapper_args,
            context=request_context,
            max_retries=max_retries,
        )
        result_payload = wrapper_response.get("result") or {}
        parsed = _coerce_search_response(result_payload)
        if parsed is None:
            raise WebContentInvalidResponseError("response")
        payload = _normalize_wrapper_payload(result_payload)
        payload["meta"] = _build_search_meta(
            payload=payload,
            request_id=request_context["request_id"],
            upstream_request_id=parsed.get("upstream_request_id"),
        )
        status = "success" if payload["status"] == "success" else "error"
    except (WebContentInvalidResponseError, ValueError, RuntimeError) as exc:
        payload = {
            "status": "error",
            "query": query,
            "results": [],
            "images": [],
            "error": map_web_tool_error(
                tool_id="web_search",
                exc=exc,
                request_id=request_context["request_id"],
                profile_id=WEB_SEARCH_PROFILE_ID,
            ),
        }
        status = "error"

    return WebSearchExecutionOutcome(
        status=status,
        payload=payload,
        prompt_tokens=0,
        completion_tokens=0,
    )
