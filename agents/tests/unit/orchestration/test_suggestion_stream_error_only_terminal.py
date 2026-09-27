"""Suggestion の生成結果が終端化するまで待つことを検証する。

期待:
    - DB が一時的に結果を返さなくても秒数で打ち切らない。
    - 終端行が保存されたら、その状態を配信して内部状態を復旧する。

背景:
    Suggestion は runtime の worker job が推論を実行し、結果は `agent_suggestions`
    を SSOT とする。WS 側は独自の時間制限を設けず、その終端状態を待つ。
"""

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
from pantaray_agents.repositories.suggestion_runtime_results import (
    AppendProcessEventResult,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult

LIVE_PROCESS = LiveSuggestionProcess(process_id="process-1", suggestion_id="s1")


@pytest.mark.asyncio
async def test_relay_waits_for_the_terminal_row_and_releases_the_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "is_mock_mode", lambda: False)
    monkeypatch.setattr(
        suggestion_job_timing,
        "SUGGESTION_JOB_POLL_INTERVAL_SECONDS",
        0.01,
    )

    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()

    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=InMemorySessionStore(max_age_seconds=3600),
        session_id="sess-1",
        user_id="user-1",
    )

    # 終端行が保存されるまで空応答が続いても、WS 側では打ち切らない。
    class FakeSuggestionRepo:
        def __init__(self) -> None:
            self.get_count = 0

        async def get_suggestion(self, *, user_id: str, suggestion_id: str):  # noqa: ANN001
            self.get_count += 1
            if self.get_count < 3:
                return RepositoryResult(data=None)
            return RepositoryResult(
                data={
                    "user_id": user_id,
                    "suggestion_id": suggestion_id,
                    "status": "error",
                    "has_suggestion": False,
                }
            )

        async def append_process_event_and_project_history(  # noqa: ANN001
            self,
            *,
            event_id: str,
            suggestion_id: str,
            user_id: str,
            event_name: str,
            payload: dict,
            action_id: str | None,
        ) -> RepositoryResult[AppendProcessEventResult]:
            _ = (event_id, suggestion_id, user_id, event_name, payload, action_id)
            return RepositoryResult(
                data=AppendProcessEventResult(sequence=1, inserted=True)
            )

    repo = FakeSuggestionRepo()
    handler._get_suggestion_repository = AsyncMock(return_value=repo)  # type: ignore[method-assign]
    handler._get_action_state_repository = AsyncMock(return_value=repo)  # type: ignore[method-assign]
    handler._register_suggestion_process(
        LIVE_PROCESS.process_id, LIVE_PROCESS.suggestion_id
    )

    await asyncio.wait_for(handler._relay_suggestion_result(LIVE_PROCESS), timeout=1.0)

    completed_payloads = [
        call.args[0]
        for call in websocket.send_json.call_args_list
        if call.args
        and isinstance(call.args[0], dict)
        and call.args[0].get("event") == "process_completed"
        and (call.args[0].get("data") or {}).get("process_id")
        == LIVE_PROCESS.process_id
    ]
    assert completed_payloads, (
        "process_completed was not emitted for error-only termination"
    )
    assert (completed_payloads[-1].get("data") or {}).get("status") == "error"
    assert repo.get_count == 3
    # 終端後はプロセスを解放し、同一セッションの後続処理を塞がない。
    assert LIVE_PROCESS.process_id not in handler._process_metadata
