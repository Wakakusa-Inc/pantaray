from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantaray_agents.agents.activity_summary_agent.persistence import (
    persist_activity_summary_response,
)
from pantaray_agents.schema.agent.activity import ActivitySummaryAgentResponse
from pantaray_agents.schema.repositories.repository import RepositoryResult
from pantaray_agents.schema.repository_errors import AgentRepositoryError


def _build_response() -> ActivitySummaryAgentResponse:
    return ActivitySummaryAgentResponse(
        summary_id="sum-1",
        user_id="user-1",
        summary_type="1h",
        summary="summary",
        thinking=None,
        period_start="2026-03-27T00:00:00Z",
        period_end="2026-03-27T01:00:00Z",
        source_ids=["log-1"],
        created_at="2026-03-27T01:00:00Z",
        status="success",
        error=None,
    )


@pytest.mark.asyncio
async def test_persist_activity_summary_response_raises_repository_error() -> None:
    repository = MagicMock()
    repository.update_activity_summary = AsyncMock(
        return_value=RepositoryResult(error="database write failed")
    )

    with pytest.raises(AgentRepositoryError, match="database write failed"):
        await persist_activity_summary_response(
            repository=repository,
            response=_build_response(),
            prompt_name="activity_summary",
            prompt_version="1.0",
            prompt_text="prompt",
        )


@pytest.mark.asyncio
async def test_persist_activity_summary_response_writes_once_on_success() -> None:
    repository = MagicMock()
    repository.update_activity_summary = AsyncMock(
        return_value=RepositoryResult(data={"summary_id": "sum-1"})
    )

    await persist_activity_summary_response(
        repository=repository,
        response=_build_response(),
        prompt_name="activity_summary",
        prompt_version="1.0",
        prompt_text="prompt",
    )

    repository.update_activity_summary.assert_awaited_once()
