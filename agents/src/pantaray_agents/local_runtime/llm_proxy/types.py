from __future__ import annotations

from dataclasses import dataclass
from typing import Required, TypedDict

from pantaray_llm.contracts.action_turn import LlmActionTurnResponse
from pantaray_llm.contracts.conversation import LlmProviderTurn
from pantaray_llm.contracts.tool_use import LlmToolCall, LlmToolContinuation
from pantaray_llm.errors.error_contract import (
    LlmProvider,
    ProxyResultOutcome,
    ProxySuggestedAction,
)


class LocalLlmProxyResultMeta(TypedDict, total=False):
    local_job_id: Required[str]
    upstream_provider: Required[LlmProvider]
    profile_id: Required[str]
    outcome: Required[ProxyResultOutcome]
    upstream_request_id: str
    suggested_action: ProxySuggestedAction


@dataclass(frozen=True, slots=True)
class ProxyResponse:
    text: str
    usage_metadata: dict[str, int] | None
    parsed: object | None = None
    meta: LocalLlmProxyResultMeta | None = None
    thinking: str | None = None
    tool_calls: tuple[LlmToolCall, ...] = ()
    dropped_tool_call_names: tuple[str, ...] = ()
    tool_continuation: LlmToolContinuation | None = None
    action_turn: LlmActionTurnResponse | None = None
    # The output items that Action turn produced, to hand back on the next one.
    # Beside ``action_turn``: that contract is closed and shared with the cloud.
    provider_turn: LlmProviderTurn | None = None


@dataclass(frozen=True, slots=True)
class ProxyStreamChunk:
    text: str
    usage_metadata: dict[str, int] | None = None
    thinking: str | None = None


__all__ = ["LocalLlmProxyResultMeta", "ProxyResponse", "ProxyStreamChunk"]
