"""ActionAgent のキャンセル検知ガード（repository 不調時の安全停止）のテスト。

目的:
    `agent_actions.status="canceled"` を DB から確認できない状態が長時間続く場合、
    無駄な LLM/ツール実行を避けるために error で安全停止できることを担保する。
"""

from __future__ import annotations

from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.agents.action_agent.runtime.state import build_next_action
from pantaray_agents.application.action.cancellation_service import (
    ActionCancellationService,
)
from pantaray_agents.application.action.use_case_service import (
    ActionUseCaseDeps,
    ActionUseCaseService,
)
from pantaray_agents.utils.prompt_loader import PromptConfig


@pytest.fixture
def action_agent() -> ActionAgent:
    """テスト用の ActionAgent を生成する。"""

    repo = MagicMock()
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        return_value=PromptConfig(prompt="", system_instruction=None),
    ):
        return ActionAgent(
            config={"llm_client": MagicMock(), "llm": {}},
            repository=repo,
        )


@pytest.fixture
def action_use_case(action_agent: ActionAgent) -> ActionUseCaseService:
    return ActionUseCaseService(ActionUseCaseDeps(agent=action_agent))


def _base_state() -> dict:
    """_check_cancellation に必要な最小 state を作る。"""

    return {
        "action_id": "act-1",
        "suggestion_id": "sug-1",
        "user_id": "user-1",
        "status": "processing",
        "errors": [],
        "next_action": build_next_action(tool=None, decided_at="T"),
        "updated_at": "T",
        "cancel_check_max_consecutive_failures": 3,
        "cancel_check_failure_grace_seconds": 60,
    }


def _set_now_provider(
    action_use_case: ActionUseCaseService,
    now_provider,
) -> None:
    action_use_case._cancellation_service = ActionCancellationService(  # noqa: SLF001
        replace(
            action_use_case._cancellation_service._deps,  # noqa: SLF001
            now_provider=now_provider,
        )
    )


@pytest.mark.asyncio
async def test_check_cancellation_stops_when_db_status_is_canceled(
    action_agent: ActionAgent,
    action_use_case: ActionUseCaseService,
) -> None:
    """DB の status=canceled を検知したら canceled で停止する。"""

    state = _base_state()
    action_agent.repository.get_action = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(error=None, data={"status": "canceled"})
    )
    _set_now_provider(
        action_use_case,
        lambda: "2025-01-01T00:00:00+00:00",
    )
    stopped = await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
    assert stopped is True
    assert state["status"] == "canceled"
    assert state["next_action"] is None
    assert state["updated_at"] == "2025-01-01T00:00:00+00:00"


@pytest.mark.asyncio
async def test_check_cancellation_does_not_stop_before_grace(
    action_agent: ActionAgent,
    action_use_case: ActionUseCaseService,
) -> None:
    """連続失敗が閾値に達しても、grace 未満なら stop しない（誤停止防止）。"""

    state = _base_state()
    action_agent.repository.get_action = AsyncMock(  # type: ignore[attr-defined]
        side_effect=ConnectionError("db down")
    )

    timestamps = iter(
        [
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:10+00:00",
            "2025-01-01T00:00:20+00:00",
        ]
    )
    _set_now_provider(action_use_case, lambda: next(timestamps))
    with patch.object(
        action_use_case._cancellation_service,  # noqa: SLF001
        "check_cancellation",
        wraps=action_use_case._cancellation_service.check_cancellation,  # noqa: SLF001
    ):
        assert (
            await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
            is False
        )
        assert (
            await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
            is False
        )
        assert (
            await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
            is False
        )

    assert state["status"] == "processing"
    assert state.get("cancel_check_consecutive_failures") == 3


@pytest.mark.asyncio
async def test_check_cancellation_stops_with_error_after_grace(
    action_agent: ActionAgent,
    action_use_case: ActionUseCaseService,
) -> None:
    """連続失敗が閾値に達し、かつ継続時間が grace を超えたら error で停止する。"""

    state = _base_state()
    action_agent.repository.get_action = AsyncMock(  # type: ignore[attr-defined]
        side_effect=ConnectionError("db down")
    )

    timestamps = iter(
        [
            "2025-01-01T00:00:00+00:00",
            "2025-01-01T00:00:30+00:00",
            "2025-01-01T00:01:01+00:00",
        ]
    )
    _set_now_provider(action_use_case, lambda: next(timestamps))
    with patch.object(
        action_use_case._cancellation_service,  # noqa: SLF001
        "check_cancellation",
        wraps=action_use_case._cancellation_service.check_cancellation,  # noqa: SLF001
    ):
        assert (
            await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
            is False
        )
        assert (
            await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
            is False
        )
        stopped = await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001

    assert stopped is True
    assert state["status"] == "error"
    assert state["next_action"] is None
    assert state.get("errors")
    assert state["errors"][-1]["error_code"] == "ACTION_CANCEL_CHECK_UNAVAILABLE"


@pytest.mark.asyncio
async def test_check_cancellation_resets_failure_counter_on_successful_read(
    action_agent: ActionAgent,
    action_use_case: ActionUseCaseService,
) -> None:
    """一度 status が読めたら連続失敗カウンタをリセットする。"""

    state = _base_state()
    state["cancel_check_consecutive_failures"] = 2
    state["cancel_check_first_failure_at"] = "2025-01-01T00:00:00+00:00"

    action_agent.repository.get_action = AsyncMock(  # type: ignore[attr-defined]
        return_value=MagicMock(error=None, data={"status": "processing"})
    )

    _set_now_provider(
        action_use_case,
        lambda: "2025-01-01T00:00:10+00:00",
    )
    stopped = await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001

    assert stopped is False
    assert state.get("cancel_check_consecutive_failures") in (None, 0)
    assert state.get("cancel_check_first_failure_at") in (None, "")


@pytest.mark.asyncio
async def test_check_cancellation_rejects_missing_policy(
    action_use_case: ActionUseCaseService,
) -> None:
    state = _base_state()
    state.pop("cancel_check_max_consecutive_failures")

    with pytest.raises(
        RuntimeError,
        match="cancel_check_max_consecutive_failures must be a positive integer",
    ):
        await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001


@pytest.mark.asyncio
async def test_check_cancellation_rejects_invalid_policy(
    action_use_case: ActionUseCaseService,
) -> None:
    state = _base_state()
    state["cancel_check_failure_grace_seconds"] = "60"

    with pytest.raises(
        RuntimeError,
        match="cancel_check_failure_grace_seconds must be a positive integer",
    ):
        await action_use_case._cancellation_service.check_cancellation(state)  # noqa: SLF001
