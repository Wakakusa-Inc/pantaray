"""ActivitySummaryAgent の出力プロトコルテスト。

要件:
- `<thinking>` / `<answer>` タグを前提にしない（本文のみを採用する）
- タグが混入しても抽出/除去は行わず、LLM出力全体を本文として扱う（fail-openではなく「仕様としてタグ前提にしない」）
"""

from __future__ import annotations

# pylint: disable=import-error,protected-access
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pantaray_agents.agents.activity_summary_agent.agent import ActivitySummaryAgent
from pantaray_agents.schema.agent.activity import (
    ActivitySummaryAgentRequest,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult
from pantaray_agents.utils.prompt_loader import PromptConfig


def _wallet_repo_with_positive_balance() -> MagicMock:
    wallet_repo = MagicMock()
    wallet_repo.get_balance_microusd = AsyncMock(return_value=RepositoryResult(data=1))
    return wallet_repo


@pytest.mark.asyncio
async def test_activity_summary_accepts_plain_text_output() -> None:
    """ActivitySummaryAgent はタグ無し本文を summary として採用する。"""

    repo = MagicMock()
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="p", system_instruction="SYS"),
    ):
        agent = ActivitySummaryAgent(
            config={
                "llm_client": MagicMock(),
                "llm": {},
                "token_wallet_repository": _wallet_repo_with_positive_balance(),
            },
            repository=repo,
        )

    agent._generate_llm_response = AsyncMock(return_value="# 1h Summary\n\nBody")  # type: ignore[method-assign]

    extracted = await agent._process_llm_response(prompt="p")

    assert extracted["summary"] == "# 1h Summary\n\nBody"


@pytest.mark.asyncio
async def test_activity_summary_preserves_tags_if_present() -> None:
    """ActivitySummaryAgent はタグを抽出/除去せず、LLM出力全体を本文として扱う。"""

    repo = MagicMock()
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="p", system_instruction="SYS"),
    ):
        agent = ActivitySummaryAgent(
            config={
                "llm_client": MagicMock(),
                "llm": {},
                "token_wallet_repository": _wallet_repo_with_positive_balance(),
            },
            repository=repo,
        )

    agent._generate_llm_response = AsyncMock(  # type: ignore[method-assign]
        return_value="<thinking>t</thinking><answer>Body</answer>"
    )

    extracted = await agent._process_llm_response(prompt="p")

    assert extracted["summary"] == "<thinking>t</thinking><answer>Body</answer>"


@pytest.mark.asyncio
async def test_activity_summary_persists_consumed_llm_thoughts() -> None:
    repo = MagicMock()
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="p", system_instruction="SYS"),
    ):
        agent = ActivitySummaryAgent(
            config={
                "llm_client": MagicMock(),
                "llm": {},
                "token_wallet_repository": _wallet_repo_with_positive_balance(),
            },
            repository=repo,
        )

    agent._generate_llm_response = AsyncMock(return_value="Summary")  # type: ignore[method-assign]
    agent._consume_llm_thoughts = MagicMock(return_value="summary thought")  # type: ignore[method-assign]

    extracted = await agent._process_llm_response(prompt="p")
    response = agent._create_success_response(
        ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="summary-1",
            summary_type="1h",
            period_start="2026-01-01T00:00:00Z",
            period_end="2026-01-01T01:00:00Z",
        ),
        extracted,
    )

    assert extracted["thinking"] == "summary thought"
    assert response.thinking == "summary thought"


@pytest.mark.asyncio
async def test_activity_summary_response_includes_source_ids_when_sources_exist() -> (
    None
):
    """ActivitySummaryAgent はソースがある場合、source_ids をレスポンスに含める。"""

    repo = MagicMock()
    # 既存レコードは無し（冪等性早期リターンを回避）
    repo.get_activity_summary = AsyncMock(  # type: ignore[attr-defined]
        return_value=RepositoryResult(data=None)
    )
    repo.get_source_data_for_summary = AsyncMock(  # type: ignore[attr-defined]
        return_value=RepositoryResult(
            data=[
                {
                    "log_id": "log-1",
                    "user_id": "u1",
                    "description": "desc",
                    "period_start": "2025-01-01T00:00:00Z",
                    "period_end": "2025-01-01T00:04:00Z",
                    "status": "success",
                }
            ]
        )
    )
    # processing行の確保が成功するよう、dataありで返す
    repo.save_activity_summary = AsyncMock(  # type: ignore[attr-defined]
        return_value=RepositoryResult(data={"summary_id": "sum-1"})
    )
    repo.update_activity_summary = AsyncMock(  # type: ignore[attr-defined]
        return_value=RepositoryResult(data={"summary_id": "sum-1"})
    )

    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="{source_data}", system_instruction="SYS"),
    ):
        agent = ActivitySummaryAgent(
            config={
                "llm_client": MagicMock(),
                "llm": {},
                "token_wallet_repository": _wallet_repo_with_positive_balance(),
            },
            repository=repo,
        )

    agent._generate_llm_response = AsyncMock(return_value="# 1h Summary\n\nBody")  # type: ignore[method-assign]

    req = ActivitySummaryAgentRequest(
        user_id="u1",
        summary_id="sum-1",
        summary_type="1h",
        period_start="2025-01-01T00:00:00Z",
        period_end="2025-01-01T01:00:00Z",
    )
    resp = await agent.process(req)

    assert resp.status == "success"
    assert resp.source_ids == ["log-1"]
