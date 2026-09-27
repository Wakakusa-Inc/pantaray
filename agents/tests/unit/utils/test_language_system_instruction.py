import os
from unittest.mock import patch

import pytest

from pantaray_agents.agents.core.base import BaseAgent
from pantaray_agents.schema.agent.base import AgentRequest, AgentResponse, JSONValue

type AgentPayload = dict[str, JSONValue]


class _DummyAgent(BaseAgent[AgentResponse]):
    def __init__(self, config: AgentPayload):
        with patch.dict(
            os.environ,
            {
                "LLM_PROXY_URL": "https://llm-proxy.test",
            },
        ):
            super().__init__(config)

    def get_response_class(self) -> type[AgentResponse]:
        return AgentResponse

    def get_error_code_prefix(self) -> str:
        return "DUMMY"

    async def _validate_request(self, request: AgentRequest) -> AgentRequest:  # type: ignore[override]
        return request

    async def _fetch_context_data(self, request: AgentRequest) -> AgentPayload:  # type: ignore[override]
        return {}

    def _build_prompt(self, context_data: AgentPayload) -> str:  # type: ignore[override]
        return ""

    async def _process_llm_response(  # type: ignore[override]
        self, prompt: str
    ) -> AgentPayload:
        return {}

    def _create_success_response(
        self, request: AgentRequest, extracted_data: AgentPayload
    ) -> AgentResponse:  # type: ignore[override]
        raise NotImplementedError

    async def _save_response(self, response: AgentResponse) -> None:  # type: ignore[override]
        raise NotImplementedError

    def _get_id_attrs(self) -> dict[str, str]:  # type: ignore[override]
        return {}

    async def _handle_agent_error(self, error, response_params):  # type: ignore[override]
        raise NotImplementedError


@pytest.fixture
def dummy_agent(mocker) -> _DummyAgent:
    return _DummyAgent(config={"llm_client": mocker.Mock()})


def test_compose_system_instruction_ja_prefix_keeps_base(
    dummy_agent: _DummyAgent,
) -> None:
    base = "BASE_SYSTEM_PROMPT"
    composed = dummy_agent._compose_system_instruction(
        base_instruction=base, language="ja"
    )  # noqa: SLF001
    assert "respond in Japanese" in composed
    assert base in composed


def test_compose_system_instruction_en_default(dummy_agent: _DummyAgent) -> None:
    base = "BASE_SYSTEM_PROMPT"
    composed = dummy_agent._compose_system_instruction(
        base_instruction=base, language=None
    )  # noqa: SLF001
    assert "respond in English" in composed
    assert base in composed
