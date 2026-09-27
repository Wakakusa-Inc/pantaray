"""Action(SSOT) の ack_event / close が local runtime 契約を守ることを固定するテスト。

期待:
    - Action ACK は session_store に保持された event_id のみを受理する。
    - local runtime 主線では legacy process-store cleanup に触れない。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

import pantaray_agents.dependencies as deps
from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws.handler import WSOrchestrationHandler
from pantaray_agents.schema.websocket import AckEventMessage


@pytest.mark.asyncio
async def test_action_ack_event_local_runtime_keeps_session_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "is_mock_mode", lambda: False)

    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()

    store = InMemorySessionStore(max_age_seconds=3600)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=store,
        session_id="sess-1",
        user_id="user-1",
    )

    process_id = "proc-1"
    store.ensure_process(handler.session_id, process_id)
    store.set_process_metadata(
        handler.session_id,
        process_id,
        suggestion_id="sug-1",
        action_id="act-1",
        kind="action",
    )
    handler._action_processes.add(process_id)

    msg = AckEventMessage(
        session_id="sess-1", process_id="proc-1", event_id="1700000000000-0"
    )
    await handler.handle_ack(msg)

    assert store.get_process_metadata(handler.session_id, process_id) is not None
    assert process_id in handler._action_processes


@pytest.mark.asyncio
async def test_close_local_runtime_releases_action_processes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(deps, "is_mock_mode", lambda: False)

    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()

    store = InMemorySessionStore(max_age_seconds=3600)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=store,
        session_id="sess-1",
        user_id="user-1",
    )
    handler._action_processes.add("proc-1")

    await handler.close()

    assert handler._action_processes == set()
