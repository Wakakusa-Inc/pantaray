"""superseded（権威なし）状態の finalize 動作テスト。"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from pantaray_agents.agents.action_agent.runtime.handlers.nodes.finalize import (
    finalize_step,
)
from pantaray_agents.agents.action_agent.runtime.state import build_next_action


@pytest.mark.asyncio
async def test_finalize_does_not_error_when_superseded_and_processing() -> None:
    """superseded かつ processing の場合でも、予期しない終了として error 化しないことを確認。"""
    agent = MagicMock()
    runtime = MagicMock()
    runtime.emit_action_step = AsyncMock()
    runtime.services = SimpleNamespace(
        cancellation=SimpleNamespace(check_cancellation=AsyncMock(return_value=False)),
        response=SimpleNamespace(build_agent_error=agent._build_agent_error),
    )

    state = {
        "phase": "finalizing",
        "status": "processing",
        "final_output": "",
        "errors": [],
        "chunks_sent": 0,
        "run_authority": "superseded",
        "skip_persist": True,
    }

    updated = await finalize_step(agent, state, runtime)  # type: ignore[arg-type]

    assert updated["status"] == "processing"
    assert updated.get("errors") == []
    runtime.emit_action_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_suppresses_output_when_canceled() -> None:
    """finalize 直前にキャンセルを検知した場合、出力送信と最終出力を抑止する。"""

    def _cancel(_state: dict) -> bool:
        _state["status"] = "canceled"
        _state["next_action"] = None
        return True

    agent = MagicMock()
    runtime = MagicMock()
    runtime.emit_action_step = AsyncMock()
    runtime.services = SimpleNamespace(
        cancellation=SimpleNamespace(check_cancellation=AsyncMock(side_effect=_cancel)),
        response=SimpleNamespace(build_agent_error=agent._build_agent_error),
    )

    state = {
        "phase": "finalizing",
        "status": "processing",
        "final_output": "SECRET_OUTPUT",
        "errors": [],
        "chunks_sent": 0,
        "run_authority": "authoritative",
        "skip_persist": False,
        "next_action": build_next_action(tool=None, decided_at="T"),
    }

    updated = await finalize_step(agent, state, runtime)  # type: ignore[arg-type]

    assert updated["status"] == "canceled"
    assert updated["final_output"] == ""
    runtime.emit_action_step.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_does_not_promote_to_success_when_fatal_error_exists() -> None:
    """fatal error が残っている場合、final_output があっても success に昇格しない。"""
    agent = MagicMock()
    agent._iter_string_chunks = MagicMock(return_value=["internal failure"])  # type: ignore[attr-defined]
    runtime = MagicMock()
    runtime.emit_action_step = AsyncMock()
    runtime.services = SimpleNamespace(
        cancellation=SimpleNamespace(check_cancellation=AsyncMock(return_value=False)),
        response=SimpleNamespace(build_agent_error=agent._build_agent_error),
    )

    state = {
        "phase": "finalizing",
        "status": "processing",
        "final_output": "internal failure",
        "errors": [
            {
                "error_type": "internal_error",
                "error_code": "GOAL_WORKER_FATAL_STOP",
                "error_message": "fatal",
                "error_details": {"reason": "persistence_failed"},
                "severity": "error",
                "metadata": None,
            }
        ],
        "chunks_sent": 0,
        "run_authority": "authoritative",
        "skip_persist": False,
    }

    updated = await finalize_step(agent, state, runtime)  # type: ignore[arg-type]

    assert updated["status"] == "error"
