"""action_agent テスト共通フィクスチャ"""

from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.mock.mock_agent_repository import MockActionAgentRepository
from pantaray_agents.mock.mock_llm_client import MockLLMClient


@pytest.fixture()
def action_agent() -> ActionAgent:
    repo = MockActionAgentRepository()
    llm_client = MockLLMClient()
    return ActionAgent(
        config={
            "supabase_client": object(),
            "llm_client": llm_client,
            "llm": {},
        },
        repository=repo,
    )
