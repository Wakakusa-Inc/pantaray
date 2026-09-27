"""ActivitySummaryAgent の生成専用契約テスト。"""

from __future__ import annotations

import sqlite3
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pantaray_agents.agents.activity_summary_agent.agent import ActivitySummaryAgent
from pantaray_agents.schema.agent.activity import (
    ActivitySummaryAgentRequest,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult
from pantaray_agents.utils.prompt_loader import PromptConfig
from pantaray_agents.utils.trace_context import get_trace_context


def _build_agent(repo: MagicMock) -> ActivitySummaryAgent:
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="p", system_instruction=None),
    ):
        return ActivitySummaryAgent(
            config={"llm_client": MagicMock(), "llm": {}},
            repository=repo,
        )


@pytest.mark.asyncio
async def test_run_without_persistence_returns_deterministic_no_activity_without_persistence() -> (
    None
):
    repo = MagicMock()
    repo.get_activity_summary = AsyncMock(
        side_effect=AssertionError("row reads must be owned by orchestration")
    )
    repo.save_activity_summary = AsyncMock(
        side_effect=AssertionError("row writes must be owned by orchestration")
    )
    repo.update_activity_summary = AsyncMock(
        side_effect=AssertionError("row writes must be owned by orchestration")
    )
    repo.get_source_data_for_summary = AsyncMock(return_value=RepositoryResult(data=[]))
    agent = _build_agent(repo)
    agent._generate_llm_response = AsyncMock(  # type: ignore[method-assign]
        side_effect=AssertionError("LLM should not be called when no sources")
    )

    response = await agent.run_without_persistence(
        ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="sum-1",
            summary_type="1h",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-01-01T01:00:00Z",
        )
    )

    assert response.status == "success"
    assert "No activity was recorded during this period." in response.summary


@pytest.mark.asyncio
async def test_run_without_persistence_sets_trace_context_for_summary_llm_path() -> (
    None
):
    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(
        return_value=RepositoryResult(
            data=[
                {
                    "log_id": "log-1",
                    "description": "work",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-01T00:04:00Z",
                }
            ]
        )
    )
    agent = _build_agent(repo)

    trace_seen: dict[str, str | None] = {"user_id": None}

    async def _fake_process(prompt: str) -> dict[str, object]:
        del prompt
        trace = get_trace_context()
        trace_seen["user_id"] = trace.user_id if trace else None
        return {"summary": "summary", "thinking": None}

    agent._process_llm_response = AsyncMock(  # type: ignore[method-assign]
        side_effect=_fake_process
    )

    response = await agent.run_without_persistence(
        ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="sum-1",
            summary_type="1h",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-01-01T01:00:00Z",
        )
    )

    assert response.status == "success"
    assert response.summary == "summary"
    assert trace_seen == {"user_id": "user-1"}


@pytest.mark.asyncio
async def test_run_without_persistence_uses_source_ids_from_context() -> None:
    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(
        return_value=RepositoryResult(
            data=[
                {
                    "log_id": "log-1",
                    "description": "work-1",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-01T00:04:00Z",
                },
                {
                    "log_id": "log-2",
                    "description": "work-2",
                    "period_start": "2025-01-01T00:04:00Z",
                    "period_end": "2025-01-01T00:08:00Z",
                },
            ]
        )
    )
    agent = _build_agent(repo)
    agent._process_llm_response = AsyncMock(  # type: ignore[method-assign]
        return_value={"summary": "summary", "thinking": None}
    )

    response = await agent.run_without_persistence(
        ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="sum-1",
            summary_type="1h",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-01-01T01:00:00Z",
        )
    )

    assert response.status == "success"
    assert response.source_ids == ["log-1", "log-2"]


@pytest.mark.asyncio
async def test_run_without_persistence_maps_fetch_context_failure_to_repository_error() -> (
    None
):
    repo = MagicMock()
    repo.save_activity_summary = AsyncMock(
        side_effect=AssertionError("row writes must be owned by orchestration")
    )
    repo.update_activity_summary = AsyncMock(
        side_effect=AssertionError("row writes must be owned by orchestration")
    )
    repo.get_source_data_for_summary = AsyncMock(side_effect=RuntimeError("boom"))
    agent = _build_agent(repo)

    response = await agent.run_without_persistence(
        ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="sum-1",
            summary_type="1h",
            period_start="2025-01-01T00:00:00Z",
            period_end="2025-01-01T01:00:00Z",
        )
    )

    assert response.status == "error"
    assert response.error is not None
    assert response.error.error_code == "ACTIVITY_SUMMARY_FETCH_CONTEXT_ERROR"


@pytest.mark.asyncio
async def test_run_without_persistence_propagates_retryable_context_failure() -> None:
    locked = sqlite3.OperationalError("database is locked")
    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(side_effect=locked)
    agent = _build_agent(repo)

    with pytest.raises(sqlite3.OperationalError) as exc_info:
        await agent.run_without_persistence(
            ActivitySummaryAgentRequest(
                user_id="user-1",
                summary_id="sum-1",
                summary_type="1h",
                period_start="2025-01-01T00:00:00Z",
                period_end="2025-01-01T01:00:00Z",
            )
        )

    assert exc_info.value is locked


_LATE_REQUEST = ActivitySummaryAgentRequest(
    user_id="user-1",
    summary_id="sum-late",
    summary_type="1h",
    period_start="2026-09-26T21:00:00Z",
    period_end="2026-09-26T22:00:00Z",
)


@pytest.mark.asyncio
@pytest.mark.usefixtures("tokyo_local_zone")
async def test_no_activity_heading_is_local_while_the_period_stays_utc() -> None:
    # 21:00Z is already the next morning in Tokyo; the heading must say the 27th.
    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(return_value=RepositoryResult(data=[]))

    response = await _build_agent(repo).run_without_persistence(_LATE_REQUEST)

    assert response.summary.startswith(
        "# 1h Summary (2026-09-27T06:00+09:00 - 2026-09-27T07:00+09:00)\n"
    )
    assert (response.period_start, response.period_end) == (
        "2026-09-26T21:00:00Z",
        "2026-09-26T22:00:00Z",
    )


@pytest.mark.asyncio
@pytest.mark.usefixtures("tokyo_local_zone")
async def test_prompt_shows_the_period_and_sources_in_local_time() -> None:
    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(
        return_value=RepositoryResult(
            data=[
                {
                    "log_id": "log-1",
                    "description": "work",
                    "period_start": "2026-09-26T21:50:00Z",
                    "period_end": "2026-09-26T21:54:00Z",
                }
            ]
        )
    )
    agent = ActivitySummaryAgent(
        config={"llm_client": MagicMock(), "llm": {}}, repository=repo
    )
    agent._process_llm_response = AsyncMock(  # type: ignore[method-assign]
        return_value={"summary": "summary", "thinking": None}
    )

    response = await agent.run_without_persistence(_LATE_REQUEST)

    (prompt,) = agent._process_llm_response.call_args.args
    assert "Times are local (Asia/Tokyo)." in prompt
    assert "- **Period**: 2026-09-27T06:00+09:00 to 2026-09-27T07:00+09:00" in prompt
    assert (
        "Source 1 (AL) Period: 2026-09-27T06:50+09:00 - 2026-09-27T06:54+09:00"
        in prompt
    )
    assert (response.period_start, response.period_end) == (
        "2026-09-26T21:00:00Z",
        "2026-09-26T22:00:00Z",
    )
