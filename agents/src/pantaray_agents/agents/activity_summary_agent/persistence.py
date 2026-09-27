from __future__ import annotations

from typing import Protocol

from pantaray_agents.schema.agent.activity import ActivitySummaryAgentResponse
from pantaray_agents.schema.repository_errors import (
    AgentRepositoryError,
    SaveResponseError,
)


class ActivitySummaryPersistencePort(Protocol):
    async def update_activity_summary(
        self,
        *,
        response: ActivitySummaryAgentResponse,
        prompt_name: str,
        prompt_version: str,
        prompt_text: str,
    ): ...


async def persist_activity_summary_response(
    *,
    repository: ActivitySummaryPersistencePort,
    response: ActivitySummaryAgentResponse,
    prompt_name: str,
    prompt_version: str,
    prompt_text: str,
) -> None:
    try:
        result = await repository.update_activity_summary(
            response=response,
            prompt_name=prompt_name,
            prompt_version=prompt_version,
            prompt_text=prompt_text,
        )
        if result.error:
            raise SaveResponseError(result.error)
    except AgentRepositoryError:
        raise
    except Exception as exc:
        raise SaveResponseError(f"activity_summary persistence failed: {exc}") from exc
