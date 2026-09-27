from __future__ import annotations

import pytest
from pydantic import BaseModel, ConfigDict

from pantaray_agents.agents.core import CountingSink
from pantaray_agents.agents.core.tool_llm_runner import ToolLlmRunner
from pantaray_agents.mock.mock_llm_client import MockLLMClient


class _StructuredResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


def _runner(client: object) -> ToolLlmRunner:
    return ToolLlmRunner(
        client=client,
        llm_config={},
        default_system_instruction="",
        error_code_prefix="TEST",
        llm_inference_profile_id="test.profile",
    )


@pytest.mark.asyncio
async def test_generate_structured_returns_validated_schema() -> None:
    client = MockLLMClient(config={})
    client.set_next_response('{"value":"ok"}')

    result = await _runner(client).generate_structured(
        sink=CountingSink(),
        prompt="test",
        response_model=_StructuredResponse,
    )

    assert result.text == '{"value":"ok"}'
    assert result.parsed == _StructuredResponse(value="ok")


@pytest.mark.asyncio
async def test_generate_structured_rejects_missing_parsed_response() -> None:
    class _Models:
        async def generate_content(self, **_kwargs: object) -> object:
            return type("Response", (), {"text": '{"value":"ok"}', "parsed": None})()

    class _Aio:
        models = _Models()

    class _Client:
        aio = _Aio()

    with pytest.raises(TypeError, match="invalid structured response"):
        await _runner(_Client()).generate_structured(
            sink=CountingSink(),
            prompt="test",
            response_model=_StructuredResponse,
        )
