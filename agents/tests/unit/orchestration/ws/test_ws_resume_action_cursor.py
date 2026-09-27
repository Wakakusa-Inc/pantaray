from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient
from tests.unit.orchestration.ws.ws_resume_action_test_helpers import (
    local_ws_app_client,
    local_ws_headers,
    patch_action_relay_authority,
    patch_action_resume_cursor,
)

from pantaray_agents.orchestration.ws import action_relay_emit_start_ops


@pytest.fixture()
def app_client(monkeypatch) -> Iterator[TestClient]:
    yield from local_ws_app_client(monkeypatch)


def test_ws_resume_action_rejects_unknown_cursor(app_client: TestClient, monkeypatch):
    """指定済み cursor が local process event に存在しない場合は先頭 replay しない。"""

    patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p1",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "processing",
            "accepted_at": "2026-03-23T00:00:00Z",
            "action_started_at": "2026-03-23T00:00:01Z",
        },
    )
    patch_action_resume_cursor(monkeypatch, cursor=None)

    started: dict[str, object] = {}

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        lambda self, **kwargs: started.update(kwargs),
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._bind_action_process",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    resume_session_id = "resume-session-action-unknown-cursor"

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        _ = ws.receive_json()  # session_started
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": resume_session_id,
                    "process_id": "p1",
                    "last_cursor": "missing-event",
                    "last_chunk_index": 0,
                    "kind": "action",
                    "action_id": "a1",
                },
            }
        )
        expired = ws.receive_json()
        assert expired["event"] == "session_expired"
        assert expired["data"]["reason"] == "resume_data_unavailable"
        assert started == {}


def test_ws_resume_action_cursor_resolution_failure_returns_dependency_error(
    app_client: TestClient, monkeypatch
):
    """cursor 解決の DB/設定エラーは handler 例外ではなく dependency error にする。"""

    patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p1",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "processing",
            "accepted_at": "2026-03-23T00:00:00Z",
            "action_started_at": "2026-03-23T00:00:01Z",
        },
    )

    def _raise_cursor_resolution_failure(*_args, **_kwargs) -> int:
        raise OSError("cursor db unavailable")

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._resolve_action_start_after_cursor",
        _raise_cursor_resolution_failure,
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    resume_session_id = "resume-session-action-cursor-resolution-failure"

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        _ = ws.receive_json()  # session_started
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": resume_session_id,
                    "process_id": "p1",
                    "last_cursor": "1-1",
                    "last_chunk_index": 0,
                    "kind": "action",
                    "action_id": "a1",
                },
            }
        )
        err = ws.receive_json()
        assert err["event"] == "error"
        data = err.get("data") or {}
        assert isinstance(data, dict)
        assert data.get("error_code") == "WS_DEPENDENCY_UNAVAILABLE"


@pytest.mark.asyncio
async def test_attach_action_process_does_not_bind_unknown_resume_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """attach helper 単体でも不明 cursor は session に bind せず fail-closed にする。"""

    calls: list[str] = []

    class _Handler:
        session_id = "session-1"

        def _bind_action_process(self, *_args, **_kwargs) -> None:
            calls.append("bind")

        def _sync_process_metadata_to_current_session(self, *_args, **_kwargs) -> None:
            calls.append("sync")

        def _start_action_event_forwarder(self, *_args, **_kwargs) -> None:
            calls.append("start")

    monkeypatch.setattr(
        action_relay_emit_start_ops,
        "read_local_runtime_db_config",
        lambda: ("/tmp/local-runtime.db", 1_000),
    )
    monkeypatch.setattr(
        action_relay_emit_start_ops,
        "resolve_local_process_event_cursor",
        lambda **_kwargs: None,
    )

    with pytest.raises(action_relay_emit_start_ops.ActionResumeCursorUnavailable):
        await action_relay_emit_start_ops._attach_action_process_to_current_session(
            _Handler(),
            process_id="p1",
            logical_run_id="p1",
            suggestion_id="s1",
            action_id="a1",
            command_id="cmd-1",
            start_event_id="missing-event",
        )

    assert calls == []
