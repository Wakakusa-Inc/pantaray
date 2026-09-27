"""LLM usage の並列実行時の競合を防ぐテスト。

背景:
    ActionAgent はツール実行を asyncio.gather で並列実行する。
    その際、同一 ActionAgent インスタンスを共有するため、LLM usage をインスタンス属性に置くと
    将来的な await の挿入等で他 Task の値に上書きされうる。

本テストでは、generate→consume の間に await を意図的に挟み、
Task-local（ContextVar）で usage を保持できていることを確認する。
"""

from __future__ import annotations

import asyncio
from unittest.mock import MagicMock

import pytest

from pantaray_agents.agents.action_agent.agent import ActionAgent
from pantaray_agents.agents.core import CountingSink


class _DummyResponse:
    def __init__(self, text: str, usage_metadata: object) -> None:
        self.text = text
        self.usage_metadata = usage_metadata


class _DummyModels:
    async def generate_content(
        self, *, contents: list[object], config: object
    ) -> _DummyResponse:  # noqa: ARG002
        # prompt は contents の最後に入る（画像無しの場合）
        prompt = contents[-1] if contents else ""
        prompt_str = prompt if isinstance(prompt, str) else ""
        if "A" in prompt_str:
            usage = {"prompt_token_count": 11, "completion_token_count": 22}
        else:
            usage = {"prompt_token_count": 33, "completion_token_count": 44}
        # 生成処理中の並列性を模擬
        await asyncio.sleep(0)
        return _DummyResponse("ok", usage)


class _DummyAio:
    def __init__(self) -> None:
        self.models = _DummyModels()


class _DummyClient:
    def __init__(self) -> None:
        self.aio = _DummyAio()


@pytest.mark.asyncio
async def test_llm_usage_is_task_local_even_if_awaited_between_generate_and_consume() -> (
    None
):
    """generate と consume の間に await があっても usage が取り違えられないことを確認する。"""

    agent = ActionAgent(
        config={"llm": {}, "llm_client": _DummyClient()},
        repository=MagicMock(),
    )

    async def _worker(tag: str) -> tuple[int | None, int | None]:
        sink = CountingSink()
        _ = await agent._generate_llm_response(
            prompt=f"prompt {tag}",
            sink=sink,
            system_instruction="x",
            stage="planning",
        )
        await asyncio.sleep(0)
        return sink.delta.prompt_tokens, sink.delta.completion_tokens

    a_usage, b_usage = await asyncio.gather(_worker("A"), _worker("B"))
    assert a_usage == (11, 22)
    assert b_usage == (33, 44)
