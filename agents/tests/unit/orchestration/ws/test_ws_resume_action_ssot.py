from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Iterator
from threading import Event

import pytest
from starlette.testclient import TestClient
from tests.unit.orchestration.ws.ws_resume_action_test_helpers import (
    local_ws_app_client,
    local_ws_headers,
)
from tests.unit.orchestration.ws.ws_resume_action_test_helpers import (
    patch_action_relay_authority as _patch_action_relay_authority,
)
from tests.unit.orchestration.ws.ws_resume_action_test_helpers import (
    patch_action_resume_cursor as _patch_action_resume_cursor,
)
from tests.unit.orchestration.ws.ws_resume_action_test_helpers import (
    register_suggestion_resume_session as _register_suggestion_resume_session,
)

from pantaray_agents.utils import metrics as ws_metrics


@pytest.fixture()
def app_client(monkeypatch) -> Iterator[TestClient]:
    yield from local_ws_app_client(monkeypatch)


def test_ws_resume_action_uses_durable_authority_and_starts_forwarder(
    app_client: TestClient, monkeypatch
):
    """durable authority と exact cursor の検証後に forwarder を起動する。"""

    _patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p-root",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "processing",
            "accepted_at": "2026-03-23T00:00:00Z",
            "action_started_at": "2026-03-23T00:00:01Z",
        },
    )
    _patch_action_resume_cursor(monkeypatch, cursor=7)

    started: dict[str, object] = {}

    def _fake_start_forwarder(self, **kwargs):  # noqa: ANN001
        started.update(kwargs)

    def _fake_bind(self, process_id: str, suggestion_id: str | None, _action_id: str):  # noqa: ANN001
        # bindが呼ばれたことを検証する
        started["bound_process_id"] = process_id
        started["bound_suggestion_id"] = suggestion_id

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        _fake_start_forwarder,
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._bind_action_process",
        _fake_bind,
        raising=False,
    )
    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        sess = ws.receive_json()
        assert sess["event"] == "session_started"
        before_req = ws_metrics.WS_RESUME_REQUESTED.labels(kind="action")._value.get()  # type: ignore[attr-defined]
        before_ok = ws_metrics.WS_RESUME_SUCCEEDED.labels(kind="action")._value.get()  # type: ignore[attr-defined]
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": "discarded-session",
                    "process_id": "p1",
                    "last_cursor": "1-1",
                    "last_chunk_index": 0,
                    "kind": "action",
                    "action_id": "a1",
                },
            }
        )
        resumed = ws.receive_json()
        assert resumed["event"] == "session_resumed"
        assert resumed["data"]["resumed_from_chunk"] == 0
        assert resumed["data"]["missing_chunks"] == []
        # forwarder起動とbindが行われる
        assert started["bound_process_id"] == "p1"
        assert started["bound_suggestion_id"] == "s1"
        assert started["process_id"] == "p1"
        assert started["logical_run_id"] == "p-root"
        assert started["suggestion_id"] == "s1"
        assert started["action_id"] == "a1"
        assert started["start_event_id"] == "1-1"
        assert started["start_after_cursor"] == 7
        after_req = ws_metrics.WS_RESUME_REQUESTED.labels(kind="action")._value.get()  # type: ignore[attr-defined]
        after_ok = ws_metrics.WS_RESUME_SUCCEEDED.labels(kind="action")._value.get()  # type: ignore[attr-defined]
        assert after_req == before_req + 1
        assert after_ok == before_ok + 1


def test_ws_resume_action_ignores_non_authoritative_client_hints(
    app_client: TestClient, monkeypatch
):
    """action_id があれば kind と関連 ID の hint は authority を上書きしない。"""
    _patch_action_relay_authority(
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
    _patch_action_resume_cursor(monkeypatch, cursor=7)

    started: dict[str, object] = {}

    def _fake_start_forwarder(self, **kwargs):  # noqa: ANN001
        started.update(kwargs)

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        _fake_start_forwarder,
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._bind_action_process",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    resume_session_id = "resume-session-kind-override"

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
                    "kind": "suggestion",
                    "suggestion_id": "wrong-suggestion",
                    "action_id": "a1",
                    "command_id": "wrong-command",
                },
            }
        )
        resumed = ws.receive_json()
        assert resumed["event"] == "session_resumed"
        assert started["process_id"] == "p1"
        assert started["suggestion_id"] == "s1"
        assert started["command_id"] == "cmd-1"


def test_ws_resume_suggestion_without_action_id_uses_existing_path(
    app_client: TestClient, monkeypatch
):
    """action_id がない Suggestion resume は既存 path を使う。"""

    resume_session_id = "resume-session-suggestion-kind-override"
    _register_suggestion_resume_session(session_id=resume_session_id)

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
                    "kind": "suggestion",
                },
            }
        )
        resumed = ws.receive_json()
        assert resumed["event"] == "session_resumed"
        assert resumed["data"]["missing_chunks"] == []


@pytest.mark.parametrize(
    ("kind", "action_id"),
    [("action", None), ("suggestion", "")],
)
def test_ws_resume_action_selection_never_falls_back_to_suggestion(
    app_client: TestClient,
    monkeypatch,
    kind: str,
    action_id: str | None,
):
    """Action selector が欠けても valid Suggestion session へfallbackしない。"""
    _patch_action_relay_authority(monkeypatch, row=None)
    session_id = "valid-suggestion-session"
    _register_suggestion_resume_session(session_id=session_id)

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        _ = ws.receive_json()  # session_started
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": session_id,
                    "process_id": "p1",
                    "last_cursor": "1-1",
                    "last_chunk_index": 0,
                    "kind": kind,
                    "action_id": action_id,
                },
            }
        )
        expired = ws.receive_json()
        assert expired["event"] == "session_expired"
        assert expired["data"]["reason"] == "resume_data_unavailable"


def test_ws_resume_action_without_live_memory_starts_durable_relay(
    app_client: TestClient,
    monkeypatch,
):
    """durable authority があれば live memory なしでも resume する。"""

    _patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p-resume",
            "root_process_id": "p-resume",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "queued",
            "suggestion_id": None,
            "accepted_at": "2026-03-23T00:00:00Z",
            "action_started_at": "2026-03-23T00:00:01Z",
        },
    )
    _patch_action_resume_cursor(monkeypatch, cursor=0)

    started: dict[str, object] = {}

    def _fake_start_forwarder(self, **kwargs):  # noqa: ANN001
        started.update(kwargs)

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        _fake_start_forwarder,
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._bind_action_process",
        lambda *_args, **_kwargs: None,
        raising=False,
    )

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        session_started = ws.receive_json()
        assert session_started["event"] == "session_started"
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": "discarded-session",
                    "process_id": "p-resume",
                    "last_cursor": None,
                    "last_chunk_index": -1,
                    "kind": "action",
                    "suggestion_id": "s1",
                    "action_id": "a1",
                    "command_id": "cmd-1",
                },
            }
        )
        response = ws.receive_json()
        assert response["event"] == "session_resumed"
        assert started["process_id"] == "p-resume"
        assert started["suggestion_id"] is None


def test_ws_resume_terminal_before_ack(app_client: TestClient, monkeypatch):
    _patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p1",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "queued",
            "terminal_cursor": 8,
        },
    )
    _patch_action_resume_cursor(monkeypatch, cursor=3)
    started: dict[str, object] = {}
    forwarder_started = Event()

    def _start_forwarder(handler, **kwargs):  # noqa: ANN001
        started.update(kwargs)
        forwarder_started.set()

        async def _complete_terminal_relay() -> None:
            handler._release_action_process("p1")

        return asyncio.create_task(_complete_terminal_relay())

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        _start_forwarder,
    )

    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations",
        headers=local_ws_headers(),
    ) as ws:
        _ = ws.receive_json()
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": "discarded-session",
                    "process_id": "p1",
                    "last_cursor": "1-1",
                    "last_chunk_index": 0,
                    "kind": "action",
                    "action_id": "a1",
                },
            }
        )
        assert forwarder_started.wait(timeout=1)
        assert started["start_event_id"] == "0-0"
        assert started["start_after_cursor"] == 7
        assert started["process_id"] == "p1"


def test_ws_resume_terminal_relay_storage_failure_returns_error(
    app_client: TestClient, monkeypatch
):
    _patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p1",
            "action_id": "a1",
            "action_command_id": "cmd-1",
            "action_status": "success",
            "terminal_cursor": 8,
        },
    )
    _patch_action_resume_cursor(monkeypatch, cursor=3)
    captured: dict[str, object] = {}
    dependency_failures: list[tuple[str, str]] = []

    def _start_forwarder(handler, **_kwargs):  # noqa: ANN001
        captured["handler"] = handler

        async def _fail_terminal_relay() -> None:
            raise sqlite3.OperationalError("database is locked")

        return asyncio.create_task(_fail_terminal_relay())

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        _start_forwarder,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.session_resume.record_ws_dependency_fail",
        lambda *, dependency, operation: dependency_failures.append(
            (dependency, operation)
        ),
    )

    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations",
        headers=local_ws_headers(),
    ) as ws:
        _ = ws.receive_json()
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": "discarded-session",
                    "process_id": "p1",
                    "last_cursor": "1-1",
                    "last_chunk_index": 0,
                    "kind": "action",
                    "action_id": "a1",
                },
            }
        )
        error = ws.receive_json()
        assert error["event"] == "error"
        assert error["data"]["error_code"] == "ACTION_RELAY_ATTACH_FAILED"
        handler = captured["handler"]
        assert "p1" not in handler._action_processes
        assert "p1" not in handler._process_metadata
        assert (
            handler.session_store.get_process_metadata(handler.session_id, "p1") is None
        )
        assert dependency_failures == [("ws_handler", "attach_action")]


def test_ws_resume_action_rejects_authority_identity_mismatch(
    app_client: TestClient, monkeypatch
):
    """durable identity が一致しない場合はresume_data_unavailableとして拒否する。"""
    _patch_action_relay_authority(
        monkeypatch,
        row={
            "action_process_id": "p1",
            "root_process_id": "p1",
            "action_id": "different-action",
            "action_command_id": "cmd-1",
            "action_status": "processing",
        },
    )
    resume_session_id = "resume-session-action-cross-user"

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        _ = ws.receive_json()  # session_started
        before_exp = ws_metrics.WS_RESUME_EXPIRED.labels(  # type: ignore[attr-defined]
            reason="resume_data_unavailable", kind="action"
        )._value.get()
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
        expired = ws.receive_json()
        assert expired["event"] == "session_expired"
        assert expired["data"]["reason"] == "resume_data_unavailable"
        after_exp = ws_metrics.WS_RESUME_EXPIRED.labels(  # type: ignore[attr-defined]
            reason="resume_data_unavailable", kind="action"
        )._value.get()
        assert after_exp == before_exp + 1


def test_ws_resume_rate_limit_exceeded_returns_error(
    app_client: TestClient, monkeypatch
):
    """同一 process_id への resume_session 過剰連打は validation_error として抑止する。"""
    _patch_action_relay_authority(
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
    _patch_action_resume_cursor(monkeypatch, cursor=7)
    # forwarder/bind は不要
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._start_action_event_forwarder",
        lambda *args, **kwargs: None,  # noqa: ANN001
        raising=False,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._bind_action_process",
        lambda *args, **kwargs: None,  # noqa: ANN001
        raising=False,
    )
    resume_session_id = "resume-session-action-rate-limit"

    headers = local_ws_headers()
    with app_client.websocket_connect(
        "/v1/agents/users/user-1/orchestrations", headers=headers
    ) as ws:
        _ = ws.receive_json()  # session_started
        payload = {
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
        # 3回までは許可される
        for _i in range(3):
            ws.send_json(payload)
            msg = ws.receive_json()
            assert msg["event"] in {"session_resumed", "session_expired"}
        # 4回目は抑止
        ws.send_json(payload)
        err = ws.receive_json()
        assert err["event"] == "error"
        data = err.get("data") or {}
        assert isinstance(data, dict)
        assert data.get("error_code") == "WS_RESUME_RETRY_LIMIT_EXCEEDED"


def test_ws_resume_action_attach_failure_returns_error(
    app_client: TestClient, monkeypatch
):
    """部分的にbindしてattach失敗してもphantom processを残さない。"""
    _patch_action_relay_authority(
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
    _patch_action_resume_cursor(monkeypatch, cursor=7)

    captured: dict[str, object] = {}
    dependency_failures: list[tuple[str, str]] = []

    def _fail_metadata_sync(handler, *_args, **_kwargs) -> None:  # noqa: ANN001, ANN003
        captured["handler"] = handler
        raise ValueError("WS session process limit exceeded")

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._sync_process_metadata_to_current_session",
        _fail_metadata_sync,
    )
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.session_resume.record_ws_dependency_fail",
        lambda *, dependency, operation: dependency_failures.append(
            (dependency, operation)
        ),
    )
    resume_session_id = "resume-session-action-attach-failure"

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
        assert data.get("error_code") == "ACTION_RELAY_ATTACH_FAILED"
        handler = captured["handler"]
        assert "p1" not in handler._action_processes
        assert "p1" not in handler._process_metadata
        assert (
            handler.session_store.get_process_metadata(handler.session_id, "p1") is None
        )
        assert dependency_failures == [("ws_handler", "attach_action")]


def test_ws_resume_action_local_state_failure_returns_error(
    app_client: TestClient, monkeypatch
):
    """local state 読み込み失敗時は suggestion resume に流さず、dependency error とする。"""
    _patch_action_relay_authority(monkeypatch, error="local state unavailable")
    resume_session_id = "resume-session-action-local-state-error"

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
