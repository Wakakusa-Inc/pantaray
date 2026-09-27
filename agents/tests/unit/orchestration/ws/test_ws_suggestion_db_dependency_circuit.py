"""Suggestion の DB 待ち合わせ例外が握りつぶされず、依存障害として明示終了することを検証する。"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

import pantaray_agents.dependencies as deps
from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws import suggestion_job_timing
from pantaray_agents.orchestration.ws.handler import WSOrchestrationHandler
from pantaray_agents.orchestration.ws.suggestion_relay import LiveSuggestionProcess
from pantaray_agents.schema.repositories.repository import RepositoryResult


@pytest.mark.asyncio
async def test_suggestion_db_read_failure_opens_circuit_and_fails_fast(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """repo.get_suggestion が連続失敗した場合、timeout にせず WS_DEPENDENCY_UNAVAILABLE で明示終了する。"""

    monkeypatch.setattr(deps, "is_mock_mode", lambda: False)
    from pantaray_agents.orchestration.ws import suggestion_stream as ss

    monkeypatch.setattr(
        suggestion_job_timing,
        "SUGGESTION_JOB_POLL_INTERVAL_SECONDS",
        0.01,
    )

    # DB repo を常に例外にする
    class _Repo:
        async def get_suggestion(self, *, user_id: str, suggestion_id: str):  # noqa: ANN001
            raise RuntimeError("DB is down")

        async def append_process_event_and_project_history(  # noqa: ANN001
            self, **_kwargs
        ) -> RepositoryResult[dict]:
            return RepositoryResult(
                data=type("_AppendResult", (), {"sequence": 1, "inserted": True})()
            )

    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()

    session_store = InMemorySessionStore(max_age_seconds=3600)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=session_store,
        session_id="sess-1",
        user_id="user-1",
    )

    # _get_suggestion_repository を差し替え
    repo = _Repo()
    handler._get_suggestion_repository = AsyncMock(return_value=repo)  # type: ignore[method-assign]
    handler._get_action_state_repository = AsyncMock(return_value=repo)  # type: ignore[method-assign]

    # circuit をテスト用に小さくする（2回でopen）
    from pantaray_agents.utils.ws_observability import CircuitBreaker

    monkeypatch.setattr(
        ss,
        "_suggestion_db_circuit",
        CircuitBreaker(
            failure_threshold=2,
            open_interval_seconds=60.0,
        ),
    )

    # 実行
    task = asyncio.create_task(
        handler._relay_suggestion_result(
            LiveSuggestionProcess(process_id="p1", suggestion_id="s1")
        )
    )
    await asyncio.wait_for(task, timeout=2.0)

    # error → process_completed(status=error) が送信される
    sent = [c.args[0] for c in websocket.send_json.call_args_list if c.args]
    events = [m.get("event") for m in sent if isinstance(m, dict)]
    assert "error" in events
    assert "process_completed" in events

    last_error = next(
        m for m in reversed(sent) if isinstance(m, dict) and m.get("event") == "error"
    )
    data = last_error.get("data") or {}
    assert isinstance(data, dict)
    assert data.get("error_code") == "WS_DEPENDENCY_UNAVAILABLE"

    last_completed = next(
        m
        for m in reversed(sent)
        if isinstance(m, dict) and m.get("event") == "process_completed"
    )
    pdata = last_completed.get("data") or {}
    assert isinstance(pdata, dict)
    assert pdata.get("status") == "error"
