from __future__ import annotations

from pantaray_agents.agents.action_agent.agent import ActionAgent
from pantaray_agents.mock.mock_agent_repository import MockActionAgentRepository
from pantaray_llm.profiles import TOOL_THINKING_PROFILE_ID


def test_tool_llm_runner_uses_thinking_cloud_profile() -> None:
    agent = ActionAgent(config={}, repository=MockActionAgentRepository())
    runner = agent.create_tool_llm_runner(tool_id="thinking")

    assert (
        runner._resolve_inference_profile_id(stage="tool::thinking")  # noqa: SLF001
        == TOOL_THINKING_PROFILE_ID
    )
