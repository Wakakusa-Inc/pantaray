"""ActionAgent の state token sink が型揺れでも破綻しないことを検証する。

目的:
    - state 由来の token 集計値（total_* / tokens_used）が None や文字列になっても
      例外を起こさず、集計不変条件を維持できる。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from pantaray_agents.agents.action_agent.agent import ActionAgent
from pantaray_agents.agents.action_agent.runtime.state import create_initial_state
from pantaray_agents.agents.action_agent.services.token_accounting_service import (
    StateTokenSink,
)
from pantaray_agents.agents.core import LlmUsage, TokenBudgetExceeded


class _DummyResponse:
    def __init__(self, text: str, usage_metadata: object) -> None:
        self.text = text
        self.usage_metadata = usage_metadata


class _DummyModels:
    async def generate_content(  # noqa: ARG002
        self, *, contents: list[object], config: object
    ) -> _DummyResponse:
        return _DummyResponse(
            "ok", {"prompt_token_count": 1, "completion_token_count": 2}
        )


class _DummyAio:
    def __init__(self) -> None:
        self.models = _DummyModels()


class _DummyClient:
    def __init__(self) -> None:
        self.aio = _DummyAio()


def _make_agent() -> ActionAgent:
    """テスト用に最小構成で ActionAgent を生成する。"""
    return ActionAgent(
        config={"llm": {}, "llm_client": _DummyClient()}, repository=MagicMock()
    )


def test_state_sink_handles_none_or_string_state_values() -> None:
    """state 内の totals/tokens_used が None/文字列でも TypeError にならず集計できること。"""
    agent = _make_agent()
    state = create_initial_state(
        user_id="u",
        suggestion_id="s",
        action_id="a",
        started_at="2024-01-01T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )

    # 型揺れを模擬（DB/マージ境界の不整合など）
    state["total_prompt_tokens"] = None  # type: ignore[assignment]
    state["total_completion_tokens"] = "4"  # type: ignore[assignment]
    state["tokens_used"] = None  # type: ignore[assignment]

    sink = StateTokenSink(agent._token_accounting_service, state)  # noqa: SLF001
    sink.record(
        LlmUsage(2, 3),
        stage="test",
        may_raise=True,
    )

    assert state["total_prompt_tokens"] == 2
    assert state["total_completion_tokens"] == 7
    assert state["tokens_used"] == 5


def test_state_sink_handles_invalid_token_counter_strings() -> None:
    """token 集計値が変換不能な文字列でも ValueError にならず 0 扱いで継続できること。"""
    agent = _make_agent()
    state = create_initial_state(
        user_id="u",
        suggestion_id="s",
        action_id="a",
        started_at="2024-01-01T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )

    # 変換不能な truthy 文字列を模擬（例: DB破損/想定外のマージ）
    state["total_prompt_tokens"] = "abc"  # type: ignore[assignment]
    state["total_completion_tokens"] = "10000.0"  # type: ignore[assignment]
    state["tokens_used"] = "oops"  # type: ignore[assignment]

    sink = StateTokenSink(agent._token_accounting_service, state)  # noqa: SLF001
    sink.record(
        LlmUsage(1, 2),
        stage="test",
        may_raise=True,
    )

    assert state["total_prompt_tokens"] == 1
    assert state["total_completion_tokens"] == 2
    assert state["tokens_used"] == 3
    assert state["errors"]
    assert state["errors"][0]["error_code"] == "ACTION_TOKEN_COUNTER_INVALID"
    assert state["errors"][0]["severity"] == "warning"


def test_state_sink_coerces_string_token_budget_and_checks_budget() -> None:
    """token_budget が文字列でも比較で TypeError にならず、超過時は error へ収束すること。"""
    agent = _make_agent()
    state = create_initial_state(
        user_id="u",
        suggestion_id="s",
        action_id="a",
        started_at="2024-01-01T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )

    # DB復元/マージ等で token_budget が文字列になったケースを模擬
    state["token_budget"] = "3"  # type: ignore[assignment]

    # 2+2=4 で budget(3) を超過 → error
    sink = StateTokenSink(agent._token_accounting_service, state)  # noqa: SLF001
    with pytest.raises(TokenBudgetExceeded):
        sink.record(LlmUsage(2, 2), stage="test", may_raise=True)

    assert state["token_budget"] == 3
    assert state["tokens_used"] == 4
    assert state["status"] == "error"


def test_state_sink_invalid_token_budget_is_treated_as_none() -> None:
    """token_budget が不正値の場合は fail-closed せず None 扱いとして継続できること。"""
    agent = _make_agent()
    state = create_initial_state(
        user_id="u",
        suggestion_id="s",
        action_id="a",
        started_at="2024-01-01T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )

    # 変換不能（例: "10000.0" / "oops" 等）を模擬
    state["token_budget"] = "oops"  # type: ignore[assignment]

    sink = StateTokenSink(agent._token_accounting_service, state)  # noqa: SLF001
    sink.record(
        LlmUsage(1, 1),
        stage="test",
        may_raise=True,
    )

    assert state["token_budget"] is None
    assert state["tokens_used"] == 2
    assert state["status"] != "error"
    assert state["errors"]
    assert state["errors"][0]["error_code"] == "ACTION_TOKEN_BUDGET_INVALID"
    assert state["errors"][0]["severity"] == "warning"
