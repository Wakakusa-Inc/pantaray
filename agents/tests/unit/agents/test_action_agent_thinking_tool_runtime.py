from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantaray_agents.agents.action_agent.runtime.handlers import tools as tools_handler
from pantaray_agents.agents.action_agent.tools.thinking_tool import THINKING_TOOL
from pantaray_agents.agents.core import CountingSink, LlmUsage


@pytest.mark.asyncio
async def test_thinking_tool_returns_plain_text_payload() -> None:
    agent = MagicMock()
    runner = MagicMock()

    async def generate_text(*, sink, **_kwargs):
        sink.record(LlmUsage(1, 2), stage="tool::thinking", may_raise=True)
        return "hello world"

    runner.generate_text = AsyncMock(side_effect=generate_text)
    agent.create_tool_llm_runner.return_value = runner
    sink = CountingSink()

    state: dict[str, object] = {"context": {}}
    result = await tools_handler._run_thinking_tool(  # type: ignore[attr-defined]
        agent=agent,
        step_id="step",
        tool_def=THINKING_TOOL,
        args={"query": "q", "context": "reference text"},
        state=state,  # type: ignore[arg-type]
        sink=sink,  # type: ignore[arg-type]
    )

    assert result.output == {"text": "hello world"}
    assert state == {"context": {}}
    agent.create_tool_llm_runner.assert_called_once_with(tool_id="thinking")
    _, kwargs = runner.generate_text.call_args
    assert kwargs["sink"] is sink
    assert kwargs["stage"] == "tool::thinking"
    # The internal reasoning tool never carries file inputs.
    assert "file_inputs" not in kwargs
    assert "## Reference\nreference text\n" in kwargs["prompt"]
    assert result.prompt_tokens == 1
    assert result.completion_tokens == 2
