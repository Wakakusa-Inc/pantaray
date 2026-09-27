"""WS relay of runtime-started Suggestion processes."""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

import pantaray_agents.dependencies as deps
from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws import suggestion_job_timing, suggestion_relay
from pantaray_agents.orchestration.ws.handler import WSOrchestrationHandler
from pantaray_agents.orchestration.ws.suggestion_relay import LiveSuggestionProcess
from pantaray_agents.repositories.suggestion_runtime_results import (
    AppendProcessEventResult,
)
from pantaray_agents.schema.repositories.repository import RepositoryResult

LIVE_PROCESS = LiveSuggestionProcess(process_id="p1", suggestion_id="s1")


class _ProcessingRepository:
    """Keeps the Suggestion row non-terminal so the relay stays attached."""

    async def get_suggestion(self, *, user_id: str, suggestion_id: str):  # noqa: ANN201
        return RepositoryResult(
            data={
                "user_id": user_id,
                "suggestion_id": suggestion_id,
                "status": "processing",
            }
        )

    async def append_process_event_and_project_history(  # noqa: ANN201
        self,
        *,
        event_id: str,
        suggestion_id: str,
        user_id: str,
        event_name: str,
        payload: dict,
        action_id: str | None,
    ):
        _ = (event_id, suggestion_id, user_id, event_name, payload, action_id)
        return RepositoryResult(
            data=AppendProcessEventResult(sequence=1, inserted=True)
        )


class _SucceededRepository(_ProcessingRepository):
    """The Suggestion row reached its terminal state after the reconnect."""

    async def get_suggestion(self, *, user_id: str, suggestion_id: str):  # noqa: ANN201
        return RepositoryResult(
            data={
                "user_id": user_id,
                "suggestion_id": suggestion_id,
                "status": "success",
                "has_suggestion": True,
                "answer": "resumed answer",
            }
        )


def _build_handler(
    monkeypatch: pytest.MonkeyPatch,
    *,
    client_state: WebSocketState,
    repository: _ProcessingRepository | None = None,
) -> tuple[WSOrchestrationHandler, MagicMock]:
    monkeypatch.setattr(deps, "is_mock_mode", lambda: False)
    monkeypatch.setattr(
        suggestion_job_timing, "SUGGESTION_JOB_POLL_INTERVAL_SECONDS", 0.01
    )
    monkeypatch.setattr(suggestion_relay, "SUGGESTION_RELAY_TICK_SECONDS", 0.01)
    monkeypatch.setattr(
        suggestion_relay,
        "read_local_runtime_db_config",
        lambda: (Path("/nonexistent/runtime.sqlite3"), 1000),
    )
    monkeypatch.setattr(
        suggestion_relay,
        "read_relayable_suggestion_processes",
        lambda **_kwargs: [LIVE_PROCESS],
    )

    websocket = MagicMock()
    websocket.client_state = client_state
    websocket.send_json = AsyncMock()
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=InMemorySessionStore(max_age_seconds=3600),
        session_id="sess-1",
        user_id="user-1",
    )
    repository = repository or _ProcessingRepository()
    handler._get_suggestion_repository = AsyncMock(return_value=repository)  # type: ignore[method-assign]
    handler._get_action_state_repository = AsyncMock(return_value=repository)  # type: ignore[method-assign]
    return handler, websocket


def _sent_events(websocket: MagicMock) -> list[str]:
    return [
        str(call.args[0].get("event"))
        for call in websocket.send_json.call_args_list
        if call.args and isinstance(call.args[0], dict)
    ]


@pytest.mark.asyncio
async def test_relay_attaches_one_runtime_process_only_once(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler, websocket = _build_handler(
        monkeypatch, client_state=WebSocketState.CONNECTED
    )
    try:
        await handler._relay_live_suggestion_processes()
        await handler._relay_live_suggestion_processes()
    finally:
        await handler.close()

    assert _sent_events(websocket).count("process_started") == 1


@pytest.mark.asyncio
async def test_relay_leaves_the_process_unattached_when_the_socket_is_gone(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler, websocket = _build_handler(
        monkeypatch, client_state=WebSocketState.DISCONNECTED
    )
    try:
        await handler._relay_live_suggestion_processes()
    finally:
        await handler.close()

    assert _sent_events(websocket) == []
    assert handler._relayed_suggestion_processes == set()
    session = handler.session_store.get("sess-1")
    assert session is not None
    assert LIVE_PROCESS.process_id not in session.processes


@pytest.mark.asyncio
async def test_a_resumed_process_is_not_relayed_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reconnect + resume_session must not double-deliver a live process."""
    handler, websocket = _build_handler(
        monkeypatch, client_state=WebSocketState.CONNECTED
    )
    store = handler.session_store
    store.create_session("sess-0", user_id="user-1")
    store.ensure_process("sess-0", LIVE_PROCESS.process_id)
    store.set_process_metadata(
        "sess-0",
        LIVE_PROCESS.process_id,
        suggestion_id=LIVE_PROCESS.suggestion_id,
        kind="suggestion",
    )

    await handler.resume_session(
        session_id="sess-0",
        process_id=LIVE_PROCESS.process_id,
        last_cursor=None,
        last_chunk_index=None,
        kind="suggestion",
    )
    await handler._relay_live_suggestion_processes()

    assert LIVE_PROCESS.process_id in handler._relayed_suggestion_processes
    assert "process_started" not in _sent_events(websocket)


@pytest.mark.asyncio
async def test_a_resumed_live_process_still_completes_on_the_new_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The previous session's relay died with its socket; the resumed one waits."""
    handler, websocket = _build_handler(
        monkeypatch,
        client_state=WebSocketState.CONNECTED,
        repository=_SucceededRepository(),
    )
    store = handler.session_store
    store.create_session("sess-0", user_id="user-1")
    store.ensure_process("sess-0", LIVE_PROCESS.process_id)
    store.set_process_metadata(
        "sess-0",
        LIVE_PROCESS.process_id,
        suggestion_id=LIVE_PROCESS.suggestion_id,
        kind="suggestion",
    )

    try:
        await handler.resume_session(
            session_id="sess-0",
            process_id=LIVE_PROCESS.process_id,
            last_cursor=None,
            last_chunk_index=None,
            kind="suggestion",
        )
        for _ in range(50):
            if "process_completed" in _sent_events(websocket):
                break
            await asyncio.sleep(0.01)
    finally:
        await handler.close()

    events = _sent_events(websocket)
    assert "process_started" not in events
    assert "suggestion_chunk" in events
    assert events.count("process_completed") == 1


@pytest.mark.asyncio
async def test_a_process_the_tick_attached_first_is_not_replaced_by_the_resume(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On reconnect the first tick usually wins the race against resume_session.

    The tick's result relay must keep running: replacing it would cancel it,
    and a cancelled relay reports the still-running process as canceled.
    """
    handler, websocket = _build_handler(
        monkeypatch, client_state=WebSocketState.CONNECTED
    )
    store = handler.session_store
    store.create_session("sess-0", user_id="user-1")
    store.ensure_process("sess-0", LIVE_PROCESS.process_id)
    store.set_process_metadata(
        "sess-0",
        LIVE_PROCESS.process_id,
        suggestion_id=LIVE_PROCESS.suggestion_id,
        kind="suggestion",
    )

    try:
        await handler._relay_live_suggestion_processes()
        await asyncio.sleep(0)  # let the tick's result relay start waiting
        await handler.resume_session(
            session_id="sess-0",
            process_id=LIVE_PROCESS.process_id,
            last_cursor=None,
            last_chunk_index=None,
            kind="suggestion",
        )
        await asyncio.sleep(0.05)
        events = _sent_events(websocket)
    finally:
        await handler.close()

    assert events.count("process_started") == 1
    assert "process_completed" not in events
