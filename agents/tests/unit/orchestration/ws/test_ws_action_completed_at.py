from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from pantaray_agents.local_runtime.runtime.action_malformed_stream_terminal import (
    MalformedActionStreamTerminalResult,
)
from pantaray_agents.orchestration.session.store import InMemorySessionStore
from pantaray_agents.orchestration.ws import (
    action_relay_emit_event_ops as event_ops,
)
from pantaray_agents.orchestration.ws import (
    action_relay_forwarder_local as local_forwarder,
)
from pantaray_agents.orchestration.ws.action_relay_shared import (
    ActionStreamPayloadValidationError,
    _ActionStreamTerminalizationResult,
    _validate_stream_end_stream_data,
)
from pantaray_agents.orchestration.ws.handler import WSOrchestrationHandler
from pantaray_agents.schema.events import OutboundEvent
from pantaray_agents.schema.websocket import AckEventMessage


@dataclass
class _FakeLocalEvent:
    cursor: int
    event_id: str
    event_type: str
    payload: dict[str, object]


class _FakeHandler:
    def __init__(self) -> None:
        self.session_id = "sess-1"
        self.user_id = "user-1"
        self._is_closed = False
        self._action_processes = {"proc-1"}
        self._process_metadata = {"proc-1": {"kind": "action", "action_id": "act-1"}}
        self.sent_events: list[str] = []
        self.sent_kwargs: dict[str, dict[str, Any]] = {}
        self.sent_data: dict[str, dict[str, object]] = {}
        self.send_result = True
        self.recorded_terminal_statuses: list[str] = []
        self.synced_process_metadata: dict[str, Any] | None = None

    async def _send(self, event: str, *_args: Any, **kwargs: Any) -> bool:
        self.sent_events.append(event)
        self.sent_kwargs[event] = dict(kwargs)
        self.sent_data[event] = _args[0].model_dump(mode="json")
        return self.send_result

    async def _send_action_error(self, *_args: Any, **_kwargs: Any) -> None:
        self.sent_events.append(OutboundEvent.ERROR.value)

    async def _replay_process_started_action(self, **_kwargs: Any) -> None:
        return

    async def _emit_process_completed_action(self, **kwargs: Any) -> bool:
        return await event_ops._emit_process_completed_action(self, **kwargs)

    def _record_action_terminal_completion_once(
        self,
        *,
        process_id: str,
        status: str,
    ) -> None:
        self.recorded_terminal_statuses.append(f"{process_id}:{status}")

    def _release_action_process(self, process_id: str) -> None:
        self._action_processes.discard(process_id)
        self._process_metadata.pop(process_id, None)

    def _sync_process_metadata_to_current_session(
        self, process_id: str, **kwargs: Any
    ) -> None:
        self.synced_process_metadata = {"process_id": process_id, **kwargs}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("event_type", "payload"),
    [
        ("stream_end", {}),
    ],
)
async def test_terminal_fallbacks_restore_session_ownership(
    monkeypatch: pytest.MonkeyPatch,
    event_type: str,
    payload: dict[str, object],
) -> None:
    store = InMemorySessionStore(max_age_seconds=3600)
    store.create_session("sess-1", user_id="user-1")
    websocket = AsyncMock(client_state=WebSocketState.CONNECTED)
    handler = WSOrchestrationHandler(
        websocket=websocket,
        session_store=store,
        session_id="sess-1",
        user_id="user-1",
    )
    handler._bind_action_process("proc-1", "sug-1", "act-1")
    session = store.get("sess-1")
    assert session is not None
    session.last_seen_at = 0.0
    store.prune()
    assert store.get("sess-1") is None

    event_id = "malformed-terminal"
    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="event-terminal",
                event_type=event_type,
                payload=payload,
            )
        ],
    )
    monkeypatch.setattr(
        local_forwarder,
        "_terminalize_malformed_local_action_stream",
        AsyncMock(
            return_value=_ActionStreamTerminalizationResult(
                terminal_status="error",
                terminal_event_id="malformed-terminal",
                error_event_id=None,
                emit_invalid_payload_error=True,
            )
        ),
    )

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
    )

    restored = store.get("sess-1")
    assert restored is not None and restored.user_id == "user-1"
    assert restored.processes["proc-1"].completed_at is not None
    assert event_id in restored.events
    assert [call.args[0]["event"] for call in websocket.send_json.await_args_list] == [
        OutboundEvent.ERROR.value,
        OutboundEvent.PROCESS_COMPLETED.value,
    ]
    await handler.handle_ack(
        AckEventMessage(session_id="sess-1", process_id="proc-1", event_id=event_id)
    )
    assert store.get_process_metadata("sess-1", "proc-1") is None


@pytest.mark.asyncio
async def test_standalone_malformed_terminal_converges_without_suggestion_diagnostic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _FakeHandler()
    repository = MagicMock()
    repository.finalize.return_value = MalformedActionStreamTerminalResult(
        terminal_status="error",
        terminal_event_id="standalone-terminal",
        emit_invalid_payload_error=True,
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="malformed-terminal",
                event_type="stream_end",
                payload={},
            )
        ],
    )
    monkeypatch.setattr(
        local_forwarder,
        "ActionMalformedStreamTerminalRepository",
        MagicMock(return_value=repository),
    )
    monkeypatch.setattr(local_forwarder, "now_utc_iso", lambda: "2026-03-24T00:03:00Z")

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id=None,
        action_id="act-1",
        command_id="cmd-1",
    )

    repository.finalize.assert_called_once_with(
        user_id="user-1",
        suggestion_id=None,
        action_id="act-1",
        process_id="proc-1",
        command_id="cmd-1",
        malformed_event_id="malformed-terminal",
        completed_at="2026-03-24T00:03:00Z",
        failure_code="ACTION_STREAM_PAYLOAD_INVALID",
        failure_message_public="Action stream payload is invalid.",
    )
    assert handler.sent_events == [OutboundEvent.PROCESS_COMPLETED.value]
    assert (
        handler.sent_data[OutboundEvent.PROCESS_COMPLETED.value]["suggestion_id"]
        is None
    )
    assert handler.recorded_terminal_statuses == ["proc-1:error"]
    assert "proc-1" not in handler._action_processes


@pytest.mark.asyncio
async def test_local_action_forwarder_replays_persisted_terminal_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _FakeHandler()

    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="event-1",
                event_type="stream_end",
                payload={
                    "status": "success",
                    "completed_at": "2025-01-01T00:04:00Z",
                    "persisted_sequence": 11,
                    "final_output": "completed result",
                },
            ),
        ],
    )

    blocked = _FakeHandler()
    blocked.send_result = False
    await local_forwarder._forward_action_events_from_local_runtime(
        blocked,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
    )
    assert "proc-1" in blocked._action_processes
    assert blocked.recorded_terminal_statuses == []

    capacity_blocked = _FakeHandler()
    capacity_blocked._sync_process_metadata_to_current_session = MagicMock(
        side_effect=ValueError("WS session process limit exceeded")
    )
    with pytest.raises(ValueError, match="process limit"):
        await local_forwarder._forward_action_events_from_local_runtime(
            capacity_blocked,
            process_id="proc-1",
            logical_run_id="run-root",
            suggestion_id="sug-1",
            action_id="act-1",
            command_id="cmd-1",
        )
    assert "proc-1" not in capacity_blocked._action_processes
    assert capacity_blocked._process_metadata["proc-1"]["action_id"] == "act-1"

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
    )

    assert handler.sent_data[OutboundEvent.PROCESS_COMPLETED.value] == {
        "kind": "action",
        "process_id": "proc-1",
        "suggestion_id": "sug-1",
        "action_id": "act-1",
        "command_id": "cmd-1",
        "status": "success",
    }
    assert (
        handler.sent_kwargs[OutboundEvent.PROCESS_COMPLETED.value][
            "persisted_sequence_override"
        ]
        == 11
    )
    assert (
        handler.sent_kwargs[OutboundEvent.PROCESS_COMPLETED.value][
            "store_in_session_store"
        ]
        is True
    )
    assert "insight_processing_started" not in handler.sent_events
    assert handler.recorded_terminal_statuses == ["proc-1:success"]
    assert "proc-1" not in handler._action_processes


@pytest.mark.asyncio
@pytest.mark.parametrize("step_kind", ["tool", "assistant"])
async def test_local_action_forwarder_binds_resumed_step_to_logical_run(
    monkeypatch: pytest.MonkeyPatch,
    step_kind: str,
) -> None:
    handler = _FakeHandler()
    read_after_cursors: list[int] = []

    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )

    def _read_events(**kwargs: Any) -> list[_FakeLocalEvent]:
        read_after_cursors.append(int(kwargs["after_cursor"]))
        return [
            _FakeLocalEvent(
                cursor=8,
                event_id="event-8",
                event_type="action_step",
                payload={
                    "action_id": "act-1",
                    "process_id": "proc-1",
                    "step_kind": step_kind,
                    "step_id": "step-1",
                    "step_number": 2,
                    **(
                        {
                            "tool_id": "shell",
                            "label": "shell",
                            "status": "processing",
                            "started_at": "2025-01-01T00:03:00Z",
                            "completed_at": None,
                        }
                        if step_kind == "tool"
                        else {"status": "success"}
                    ),
                },
            ),
            _FakeLocalEvent(
                cursor=9,
                event_id="event-9",
                event_type="stream_end",
                payload={
                    "status": "success",
                    "completed_at": "2025-01-01T00:04:00Z",
                    "persisted_sequence": 12,
                    "final_output": "completed result",
                },
            ),
        ]

    monkeypatch.setattr(
        local_forwarder, "read_local_process_events_after", _read_events
    )

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
        start_after_cursor=7,
    )

    assert read_after_cursors == [7]
    assert handler.sent_data[OutboundEvent.ACTION_STEP.value]["process_id"] == "proc-1"
    assert handler.sent_data[OutboundEvent.ACTION_STEP.value]["step_kind"] == step_kind
    assert "logical_run_id" not in handler.sent_data[OutboundEvent.ACTION_STEP.value]
    assert handler.sent_kwargs[OutboundEvent.ACTION_STEP.value]["meta"] == {
        "process_id": "proc-1",
        "suggestion_id": "sug-1",
        "action_id": "act-1",
        "command_id": "cmd-1",
        "kind": "action",
        "logical_run_id": "run-root",
    }
    assert handler.sent_kwargs[OutboundEvent.PROCESS_COMPLETED.value]["event_id"] == (
        "event-9"
    )


@pytest.mark.asyncio
async def test_local_action_forwarder_releases_paused_process_when_sync_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _FakeHandler()
    sync_metadata = MagicMock(
        side_effect=ValueError("WS session process limit exceeded")
    )
    handler._sync_process_metadata_to_current_session = sync_metadata

    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder, "_pause_anchor_still_holds", lambda **_kwargs: True
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="event-paused",
                event_type="process_paused",
                payload={
                    "status": "processing",
                    "reason": "approval_pending",
                    "completed_at": "2025-01-01T00:04:00Z",
                    "approval_blockers": [
                        {
                            "action_id": "act-1",
                            "approval_session_id": "approval-1",
                            "tool_request_id": "tool-request-1",
                            "tool_id": "bash",
                            "intent_class": "process_exec_local",
                            "command_summary": {"kind": "bash", "command": "pwd"},
                        }
                    ],
                },
            )
        ],
    )

    with pytest.raises(ValueError, match="process limit"):
        await local_forwarder._forward_action_events_from_local_runtime(
            handler,
            process_id="proc-1",
            logical_run_id="run-root",
            suggestion_id=None,
            action_id="act-1",
            command_id="cmd-1",
        )

    assert handler.sent_events == []
    sync_metadata.assert_called_once_with(
        "proc-1",
        suggestion_id=None,
        action_id="act-1",
        command_id="cmd-1",
        kind="action",
    )
    assert handler.recorded_terminal_statuses == []
    assert "proc-1" not in handler._action_processes
    assert handler._process_metadata["proc-1"]["action_id"] == "act-1"


@pytest.mark.asyncio
@pytest.mark.parametrize("suggestion_id", [None, "sug-1"])
async def test_local_action_forwarder_emits_new_terminal_event_without_sequence(
    monkeypatch: pytest.MonkeyPatch,
    suggestion_id: str | None,
) -> None:
    handler = _FakeHandler()

    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="event-2",
                event_type="stream_end",
                payload={
                    "status": "success",
                    "completed_at": "2025-01-01T00:04:00Z",
                    "final_output": "completed result",
                },
            )
        ],
    )

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id=suggestion_id,
        action_id="act-1",
        command_id="cmd-1",
    )

    assert handler.sent_data[OutboundEvent.PROCESS_COMPLETED.value] == {
        "kind": "action",
        "process_id": "proc-1",
        "suggestion_id": suggestion_id,
        "action_id": "act-1",
        "command_id": "cmd-1",
        "status": "success",
    }
    assert (
        handler.sent_kwargs[OutboundEvent.PROCESS_COMPLETED.value][
            "persist_public_event"
        ]
        is False
    )
    assert "insight_processing_started" not in handler.sent_events
    assert handler.recorded_terminal_statuses == ["proc-1:success"]


@pytest.mark.asyncio
@pytest.mark.parametrize("suggestion_id", [None, "sug-1"])
@pytest.mark.parametrize("send_result", [True, False])
async def test_local_action_forwarder_sends_process_only_terminal_before_release(
    monkeypatch: pytest.MonkeyPatch,
    suggestion_id: str | None,
    send_result: bool,
) -> None:
    handler = _FakeHandler()
    handler.send_result = send_result
    completed_metrics: list[str] = []
    monkeypatch.setattr(
        local_forwarder,
        "record_action_job_completed",
        lambda *, status: completed_metrics.append(status),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="skip-terminal",
                event_type="stream_end",
                payload={
                    "status": "canceled",
                    "failure_code": "ACTION_START_ALREADY_PROCESSING",
                    "failure_stage": "start_failed",
                    "failure_message_public": "Action execution was canceled.",
                    "physical_run_only": True,
                },
            )
        ],
    )

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id=suggestion_id,
        action_id="act-1",
        command_id="cmd-1",
    )

    assert handler.sent_events == [OutboundEvent.PROCESS_COMPLETED.value]
    assert handler.sent_data[OutboundEvent.PROCESS_COMPLETED.value] == {
        "kind": "action",
        "physical_run_only": True,
        "process_id": "proc-1",
        "status": "canceled",
    }
    assert handler.sent_kwargs[OutboundEvent.PROCESS_COMPLETED.value] == {
        "process_id": "proc-1",
        "meta": {"kind": "action"},
        "event_id": "skip-terminal",
        "store_in_session_store": True,
        "persist_public_event": False,
    }
    if send_result:
        assert completed_metrics == ["canceled"]
        assert handler.recorded_terminal_statuses == ["proc-1:canceled"]
        assert "proc-1" not in handler._action_processes
    else:
        assert completed_metrics == []
        assert handler.recorded_terminal_statuses == []
        assert "proc-1" in handler._action_processes


@pytest.mark.parametrize(
    "invalid_detail",
    [{"persisted_sequence": 1}, {"final_output": "unexpected"}],
)
def test_physical_run_only_terminal_rejects_conflicting_detail(
    invalid_detail: dict[str, object],
) -> None:
    with pytest.raises(ActionStreamPayloadValidationError, match="physical"):
        _validate_stream_end_stream_data(
            {
                "status": "canceled",
                "failure_code": "ACTION_START_ALREADY_PROCESSING",
                "failure_stage": "start_failed",
                "failure_message_public": "Action execution was canceled.",
                "physical_run_only": True,
                **invalid_detail,
            }
        )


@pytest.mark.asyncio
async def test_local_action_forwarder_does_not_publish_internal_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _FakeHandler()
    monkeypatch.setattr(
        local_forwarder,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1000),
    )
    monkeypatch.setattr(
        local_forwarder,
        "read_local_process_events_after",
        lambda **_kwargs: [
            _FakeLocalEvent(
                cursor=1,
                event_id="diagnostic-error",
                event_type="error",
                payload={"error_code": "ACTION_INTERNAL_DIAGNOSTIC"},
            ),
            _FakeLocalEvent(
                cursor=2,
                event_id="terminal-error",
                event_type="stream_end",
                payload={
                    "status": "error",
                    "completed_at": "2025-01-01T00:04:00Z",
                    "failure_code": "ACTION_RUNTIME_FAILED",
                    "persisted_sequence": 4,
                },
            ),
        ],
    )

    await local_forwarder._forward_action_events_from_local_runtime(
        handler,
        process_id="proc-1",
        logical_run_id="run-root",
        suggestion_id="sug-1",
        action_id="act-1",
        command_id="cmd-1",
    )

    assert OutboundEvent.ERROR.value not in handler.sent_events
    assert OutboundEvent.PROCESS_COMPLETED.value in handler.sent_events
