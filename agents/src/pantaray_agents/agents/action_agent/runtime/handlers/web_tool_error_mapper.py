from __future__ import annotations

from typing import cast

from pantaray_agents.local_runtime.web_tools.client import (
    WebContentExecutionError,
    WebContentInvalidResponseError,
)
from pantaray_llm.errors import (
    PROXY_INVALID_UPSTREAM_RESPONSE,
    ProxyAgentErrorPayload,
    ProxyProvider,
    ProxySurfaceId,
    build_proxy_agent_error,
)


def map_web_tool_error(
    *,
    tool_id: str,
    exc: Exception,
    request_id: str | None = None,
    profile_id: str | None = None,
) -> ProxyAgentErrorPayload:
    surface_id = cast(ProxySurfaceId, tool_id)
    if isinstance(exc, WebContentExecutionError):
        return build_proxy_agent_error(
            surface_id=surface_id,
            error_code=exc.error_code,
            request_id=exc.request_id or request_id,
            upstream_provider=exc.upstream_provider or _tool_provider(tool_id),
            upstream_request_id=exc.upstream_request_id,
            profile_id=exc.profile_id or profile_id,
            upstream_code=exc.upstream_code,
            upstream_status_code=exc.upstream_status_code,
            suggested_action=exc.suggested_action,
        )
    if isinstance(exc, (WebContentInvalidResponseError, ValueError)):
        return build_proxy_agent_error(
            surface_id=surface_id,
            error_code=PROXY_INVALID_UPSTREAM_RESPONSE,
            request_id=request_id,
            upstream_provider=_tool_provider(tool_id),
            profile_id=profile_id,
        )
    return build_proxy_agent_error(
        surface_id=surface_id,
        error_code=PROXY_INVALID_UPSTREAM_RESPONSE,
        request_id=request_id,
        upstream_provider=_tool_provider(tool_id),
        profile_id=profile_id,
    )


def _tool_provider(tool_id: str) -> ProxyProvider:
    _ = tool_id
    return "tavily"


__all__ = ["map_web_tool_error"]
