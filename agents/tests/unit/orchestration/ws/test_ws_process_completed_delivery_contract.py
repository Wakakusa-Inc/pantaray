from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws.action_relay_emit_ops import (
    _send_process_completed_action,
    _send_process_started_action,
)
from pantaray_agents.orchestration.ws.base import BaseWSHandler
from pantaray_agents.orchestration.ws.suggestion_stream.events import (
    SuggestionStreamEventsMixin,
)
from pantaray_agents.schema.events import OutboundEvent


class _SuggestionProcessCompletedHandler(SuggestionStreamEventsMixin, BaseWSHandler):
    pass


def _build_failing_websocket() -> MagicMock:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock(side_effect=RuntimeError("ws send failed"))
    return websocket


def _build_connected_websocket() -> MagicMock:
    websocket = MagicMock()
    websocket.client_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock()
    return websocket


def _build_session_store(
    *, process_id: str, kind: str, max_events: int | None = None
) -> InMemorySessionStore:
    session_store = InMemorySessionStore(
        max_age_seconds=3600, max_events_per_session=max_events
    )
    session_store.create_session("sess-1", user_id="user-1")
    session_store.set_process_metadata(
        "sess-1",
        process_id,
        suggestion_id="sug-1",
        action_id="act-1" if kind == "action" else None,
        command_id="cmd-1" if kind == "action" else None,
        kind=kind,
    )
    return session_store


@pytest.mark.asyncio
async def test_action_process_completed_send_json_failure_does_not_mark_completion_emitted() -> (
    None
):
    handler = BaseWSHandler(
        websocket=_build_failing_websocket(),
        session_store=_build_session_store(process_id="proc-1", kind="action"),
        session_id="sess-1",
        user_id="user-1",
    )

    sent = await _send_process_completed_action(
        handler,
        process_id="proc-1",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
        status="success",
    )

    proc = handler.session_store.get("sess-1").processes["proc-1"]
    assert sent is False
    assert proc.completed_at is None
    assert handler._is_closed is True


def test_action_terminal_reserves_ack_metadata_at_event_capacity() -> None:
    store = _build_session_store(process_id="proc-1", kind="action", max_events=1)
    store.record_event_meta("sess-1", "occupied", None, None)

    for event_id in ("terminal-1", "terminal-2"):
        store.record_event_meta(
            "sess-1",
            event_id,
            process_id="proc-1",
            chunk_index=None,
            event_name=OutboundEvent.PROCESS_COMPLETED.value,
        )
    assert set(store.get("sess-1").events) == {"occupied", "terminal-2"}


@pytest.mark.asyncio
async def test_suggestion_process_completed_send_json_failure_does_not_mark_completion_emitted() -> (
    None
):
    handler = _SuggestionProcessCompletedHandler(
        websocket=_build_failing_websocket(),
        session_store=_build_session_store(process_id="proc-1", kind="suggestion"),
        session_id="sess-1",
        user_id="user-1",
    )

    sent = await handler._emit_process_completed(
        "proc-1",
        "sug-1",
        status="success",
        has_suggestion=True,
        kind="suggestion",
    )

    proc = handler.session_store.get("sess-1").processes["proc-1"]
    assert sent is False
    assert proc.completed_at is None
    assert handler._is_closed is True


@pytest.mark.asyncio
async def test_action_process_completed_sends_identity_without_public_append() -> None:
    websocket = _build_connected_websocket()
    handler = BaseWSHandler(
        websocket=websocket,
        session_store=_build_session_store(process_id="proc-1", kind="action"),
        session_id="sess-1",
        user_id="user-1",
    )
    persist_public_event = AsyncMock(return_value=7)
    handler._persist_public_process_event_if_needed = persist_public_event

    await _send_process_completed_action(
        handler,
        process_id="proc-1",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
        status="success",
    )

    sent_payload = websocket.send_json.await_args.args[0]
    assert sent_payload["data"] == {
        "kind": "action",
        "process_id": "proc-1",
        "suggestion_id": "sug-1",
        "action_id": "act-1",
        "command_id": "cmd-1",
        "status": "success",
    }
    persist_public_event.assert_not_awaited()


@pytest.mark.asyncio
async def test_action_lifecycle_meta_carries_the_process_identity() -> None:
    """クライアントの requireMatchingEventIdentity は meta.process_id を要求する。"""
    websocket = _build_connected_websocket()
    handler = BaseWSHandler(
        websocket=websocket,
        session_store=_build_session_store(process_id="proc-1", kind="action"),
        session_id="sess-1",
        user_id="user-1",
    )
    handler._persist_public_process_event_if_needed = AsyncMock(return_value=7)

    assert await _send_process_started_action(
        handler,
        process_id="proc-1",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
        accepted_at="2026-01-01T00:00:00+00:00",
        started_at="2026-01-01T00:00:01+00:00",
    )
    assert await _send_process_completed_action(
        handler,
        process_id="proc-1",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
        status="success",
    )

    metas = [call.args[0]["meta"] for call in websocket.send_json.await_args_list]
    assert [meta["process_id"] for meta in metas] == ["proc-1", "proc-1"]
