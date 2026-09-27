"""superseded/skip_persist による永続化抑止のユニットテスト。"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from tests.unit.agents.action_agent.fixtures import build_action_request

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.application.action.use_case_service import (
    ActionUseCaseDeps,
    ActionUseCaseService,
)
from pantaray_agents.mock.mock_agent_repository import MockActionAgentRepository
from pantaray_agents.mock.mock_llm_client import MockLLMClient
from pantaray_agents.utils.prompt_loader import PromptConfig


@pytest.mark.asyncio
async def test_run_graph_skips_persist_when_skip_persist_true() -> None:
    """skip_persist=True の場合、最終永続化（save_action）を呼ばないことを確認。"""

    async def dummy_runner(state):
        state["skip_persist"] = True
        state["run_authority"] = "superseded"
        return state

    repo = MockActionAgentRepository()
    llm = MockLLMClient()

    def _fake_load_config(prompt_name: str) -> PromptConfig:
        if prompt_name == "action/executing":
            return PromptConfig(prompt="{current_time}", system_instruction="SYS")
        return PromptConfig(prompt="{current_time}", system_instruction="SYS")

    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        side_effect=_fake_load_config,
    ):
        agent = ActionAgent(config={"llm_client": llm}, repository=repo)
        agent.client = llm
    action_use_case = ActionUseCaseService(ActionUseCaseDeps(agent=agent))

    await repo.upsert_action_header(
        action_id="act-123",
        user_id="user-123",
        suggestion_id="sug-123",
        prompt_name="action/executing",
        prompt_version="1.0",
    )
    repo.save_action = AsyncMock(return_value=None)

    req = build_action_request(
        action_id="act-123",
        suggestion_id="sug-123",
        user_id="user-123",
    )

    async def noop(_event):
        return None

    # build_action_agent_graph は _run_graph の実行時に参照されるため、ここでパッチする。
    with (
        patch(
            "pantaray_agents.agents.action_agent.agent.build_action_agent_graph",
            return_value=dummy_runner,
        ),
        patch.object(
            action_use_case._execution_service,  # noqa: SLF001
            "attach_local_execution_context_if_required",
            return_value=None,
        ),
    ):
        await action_use_case._entrypoint.run_graph(  # noqa: SLF001
            req, emit_action_step=noop, emit_error=noop
        )

    repo.save_action.assert_not_awaited()
