from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pantaray_agents.dependencies as deps
from pantaray_agents.agents.activity_summary_agent.agent import ActivitySummaryAgent
from pantaray_agents.local_runtime.runtime.activity_local_repository import (
    SQLiteActivityRuntimeRepository,
)
from pantaray_agents.schema.agent.activity import (
    ActivitySummaryAgentRequest,
    ActivitySummaryAgentResponse,
)
from pantaray_agents.schema.agent.base import AgentResponse, JSONValue
from pantaray_agents.settings_loader import load_active_settings

type ActivityAgentConfig = dict[str, JSONValue]


@dataclass(frozen=True)
class ActivitySummaryExecutionResult:
    response: ActivitySummaryAgentResponse
    prompt_text: str


async def run_local_activity_summary_agent(
    *,
    request: ActivitySummaryAgentRequest,
    db_path: str,
    busy_timeout_ms: int,
) -> ActivitySummaryExecutionResult:
    agent = await _build_activity_summary_agent(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )
    response = await agent.run_without_persistence(request)
    return ActivitySummaryExecutionResult(
        response=_require_response_type(response, ActivitySummaryAgentResponse),
        prompt_text=agent.last_prompt_text,
    )


async def _build_activity_summary_agent(
    *,
    db_path: str,
    busy_timeout_ms: int,
) -> ActivitySummaryAgent:
    repository = SQLiteActivityRuntimeRepository(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )
    return ActivitySummaryAgent(
        config=await _build_activity_agent_config(),
        repository=repository,
    )


async def _build_activity_agent_config() -> ActivityAgentConfig:
    llm_client = deps.get_llm_client()
    settings = _load_current_settings()
    return {
        "mode": "local_runtime",
        "llm_client": llm_client,
        "llm": settings.get("llm", {}) if isinstance(settings.get("llm"), dict) else {},
    }


def _load_current_settings() -> dict[str, JSONValue]:
    return cast(dict[str, JSONValue], load_active_settings())


def _require_response_type[T: AgentResponse](
    response: object,
    response_class: type[T],
) -> T:
    if not isinstance(response, response_class):
        raise TypeError(
            f"Expected {response_class.__name__}, got {type(response).__name__}"
        )
    return response
