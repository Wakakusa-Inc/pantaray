"""ActivitySummaryAgent のバリアントキー伝搬テスト。

目的:
- ActivitySummaryAgent が下位サマリ取得時に prompt_name / prompt_version（バリアントキー）を
  Repository に必ず渡すこと。

背景:
- A/B テスト時に異なるプロンプト由来の下位サマリが混ざると、上位サマリが不安定になる。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pantaray_agents.agents.activity_summary_agent.agent import ActivitySummaryAgent
from pantaray_agents.schema.agent.activity import ActivitySummaryAgentRequest
from pantaray_agents.schema.repositories.repository import RepositoryResult
from pantaray_agents.utils.prompt_loader import PromptConfig


@pytest.mark.asyncio
async def test_fetch_context_passes_variant_key_to_repository() -> None:
    """_fetch_context_data が prompt_name / prompt_version を必ず渡すこと。"""

    repo = MagicMock()
    repo.get_source_data_for_summary = AsyncMock(return_value=RepositoryResult(data=[]))

    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="p", system_instruction=None),
    ):
        agent = ActivitySummaryAgent(
            config={"llm_client": MagicMock(), "llm": {}},
            repository=repo,
        )

    req = ActivitySummaryAgentRequest(
        user_id="u1",
        summary_id="sum-1",
        summary_type="24h",
        period_start="2025-01-01T00:00:00Z",
        period_end="2025-01-02T00:00:00Z",
    )

    await agent._fetch_context_data(req)

    repo.get_source_data_for_summary.assert_awaited_once_with(
        user_id="u1",
        summary_type="24h",
        period_start="2025-01-01T00:00:00Z",
        period_end="2025-01-02T00:00:00Z",
        prompt_name=ActivitySummaryAgent.PROMPT_NAME,
        prompt_version=ActivitySummaryAgent.PROMPT_VERSION,
    )
