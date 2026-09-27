from __future__ import annotations

import asyncio
import sqlite3
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from pantaray_agents.local_runtime.runtime import (
    action_messages,
    session_store,
)
from pantaray_agents.local_runtime.storage import migrations
from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws import handler_process_control
from pantaray_agents.orchestration.ws.action_relay_authority import (
    load_action_relay_authority,
)
from pantaray_agents.orchestration.ws.handler import WSOrchestrationHandler
from pantaray_agents.routers.action_cancel_service import execute_action_cancel
from pantaray_agents.schema.agent import action
from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket import AckEventMessage

_BUSY_TIMEOUT_MS = 1_000


@pytest.fixture(autouse=True)
def _reset_active_session() -> None:
    session_store.reset_desktop_session_store()
    yield
    session_store.reset_desktop_session_store()


def _bootstrap_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runtime.db"
    migrations.apply_migrations(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        migrations=migrations.load_default_migrations(),
    )
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", str(_BUSY_TIMEOUT_MS))
    session_store.import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        user_id="user-1",
        desktop_access_token="header.payload.signature",
        expires_at="2099-08-16T00:00:00Z",
        session_version="1",
    )
    return db_path


def _submit(
    *, message_id: str = "message-standalone", suggestion_id: str | None = None
):
    approval = None
    if suggestion_id:
        approval = action.SuggestionApprovalInput(
            suggestion_id=suggestion_id, approved_at="2026-08-16T00:00:01Z"
        )
    return action_messages.submit_action_message(
        action_messages.SubmitActionMessageCommand(
            user_id="user-1",
            target=action_messages.NewActionTarget(suggestion_id=suggestion_id),
            message=action.ActionUserMessageInput(
                message_id=message_id,
                content="Do the work",
                suggestion_approval=approval,
            ),
        )
    )


async def _wait_for_release(handler: WSOrchestrationHandler, process_id: str) -> None:
    while process_id in handler._action_processes:
        await asyncio.sleep(0)


@pytest.mark.asyncio
async def test_bound_paused_action_stop_uses_canonical_cancel_without_reconstruction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path = _bootstrap_runtime(tmp_path, monkeypatch)
    turn = _submit()
    with sqlite3.connect(db_path) as connection:
        connection.execute("UPDATE agent_actions SET status = 'processing'")
        connection.execute("UPDATE processes SET status = 'paused'")
        connection.execute("UPDATE jobs SET status = 'paused'")
    store = InMemorySessionStore(max_age_seconds=3600)
    websocket = AsyncMock(client_state=WebSocketState.CONNECTED)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=store,
        session_id="sess-1",
        user_id="user-1",
    )

    store.create_session(handler.session_id, user_id="user-1")
    store.set_process_metadata(
        handler.session_id,
        turn.process_id,
        action_id=turn.action_id,
        kind="action",
    )
    assert turn.process_id not in handler._action_processes

    await handler.handle_stop_process(turn.process_id)

    await asyncio.wait_for(_wait_for_release(handler, turn.process_id), timeout=1)

    terminal = load_action_relay_authority(
        user_id="user-1", action_id=turn.action_id, process_id=turn.process_id
    )
    assert terminal.action_status == "canceled" and terminal.terminal_cursor is not None
    assert [call.args[0]["event"] for call in websocket.send_json.await_args_list] == [
        OutboundEvent.PROCESS_COMPLETED.value
    ]
    assert (session := store.get(handler.session_id)) is not None
    assert session.processes[turn.process_id].completed_at is not None
    terminal_event_id = websocket.send_json.await_args_list[0].args[0]["event_id"]
    await handler.handle_ack(
        AckEventMessage(
            session_id=handler.session_id,
            process_id=turn.process_id,
            event_id=terminal_event_id,
        )
    )
    assert turn.process_id not in session.processes

    session = store.get(handler.session_id)
    assert session is not None
    session.last_seen_at = 0
    store.prune()
    assert store.get(handler.session_id) is None

    missing_session = _submit(message_id="message-missing-session")
    handler._bind_action_process(
        missing_session.process_id,
        None,
        missing_session.action_id,
    )
    await handler.handle_stop_process(missing_session.process_id)

    await asyncio.wait_for(
        _wait_for_release(handler, missing_session.process_id), timeout=1
    )
    missing_session_terminal = load_action_relay_authority(
        user_id="user-1",
        action_id=missing_session.action_id,
        process_id=missing_session.process_id,
    )
    assert missing_session_terminal.action_status == "canceled"
    restored = store.get(handler.session_id)
    assert restored is not None and restored.user_id == "user-1"
    restored_process = restored.processes[missing_session.process_id]
    assert restored_process.action_id == missing_session.action_id
    assert restored_process.completed_at is not None

    store.create_session(handler.session_id, user_id=None)
    recreated = store.get(handler.session_id)
    assert recreated is not None and recreated.user_id is None

    regenerated = _submit(message_id="message-regenerated")
    handler._bind_action_process(
        regenerated.process_id,
        None,
        regenerated.action_id,
    )
    store.set_process_metadata(
        handler.session_id,
        regenerated.process_id,
        action_id=regenerated.action_id,
        kind="action",
    )
    handler._release_action_process(regenerated.process_id)
    await handler.handle_stop_process(regenerated.process_id)

    await asyncio.wait_for(
        _wait_for_release(handler, regenerated.process_id), timeout=1
    )
    regenerated_terminal = load_action_relay_authority(
        user_id="user-1",
        action_id=regenerated.action_id,
        process_id=regenerated.process_id,
    )
    assert regenerated_terminal.action_status == "canceled"
    regenerated_session = store.get(handler.session_id)
    assert regenerated_session is not None
    assert regenerated_session.user_id == "user-1"
    assert (
        regenerated_session.processes[regenerated.process_id].completed_at is not None
    )


@pytest.mark.asyncio
async def test_stop_retries_committed_terminal_delivery_without_recanceling(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _bootstrap_runtime(tmp_path, monkeypatch)
    turn = _submit(message_id="message-terminal")
    cancel = AsyncMock(wraps=execute_action_cancel)
    monkeypatch.setattr(handler_process_control, "execute_action_cancel", cancel)

    store = InMemorySessionStore(max_age_seconds=3600)
    websocket = AsyncMock(client_state=WebSocketState.CONNECTED)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=store,
        session_id="sess-1",
        user_id="user-1",
    )
    store.create_session(handler.session_id, user_id="user-1")
    store.set_process_metadata(
        handler.session_id,
        turn.process_id,
        action_id=turn.action_id,
        kind="action",
    )
    start_forwarder = handler._start_action_event_forwarder
    blocked_forwarder = MagicMock()
    monkeypatch.setattr(handler, "_start_action_event_forwarder", blocked_forwarder)

    await handler.handle_stop_process(turn.process_id)
    cancel.assert_awaited_once()
    assert cancel.await_args.kwargs["expected_process_id"] == turn.process_id
    assert blocked_forwarder.call_args.kwargs["logical_run_id"] == turn.process_id
    assert websocket.send_json.await_args_list == []
    assert (process := store.get(handler.session_id)) is not None
    assert process.processes[turn.process_id].completed_at is None

    monkeypatch.setattr(handler, "_start_action_event_forwarder", start_forwarder)
    await handler.handle_stop_process(turn.process_id)

    await asyncio.wait_for(_wait_for_release(handler, turn.process_id), timeout=1)
    cancel.assert_awaited_once()
    assert [call.args[0]["event"] for call in websocket.send_json.await_args_list] == [
        OutboundEvent.PROCESS_COMPLETED.value
    ]

    await handler.handle_stop_process(turn.process_id)
    assert len(websocket.send_json.await_args_list) == 1

    racing = _submit(message_id="message-racing-terminal")
    handler._bind_action_process(racing.process_id, None, racing.action_id)

    async def _cancel_after_concurrent_delivery(**kwargs):  # noqa: ANN003, ANN202
        await execute_action_cancel(**kwargs)
        handler._record_action_terminal_completion_once(
            process_id=racing.process_id, status="canceled"
        )
        handler._release_action_process(racing.process_id)
        store.discard_completed_process(handler.session_id, racing.process_id)

    monkeypatch.setattr(
        handler_process_control,
        "execute_action_cancel",
        _cancel_after_concurrent_delivery,
    )
    duplicate_relay = MagicMock()
    monkeypatch.setattr(handler, "_start_action_event_forwarder", duplicate_relay)

    await handler.handle_stop_process(racing.process_id)

    duplicate_relay.assert_not_called()
