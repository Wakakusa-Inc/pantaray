import pytest
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from .shared import (
    ORCHESTRATIONS_PATH,
    WS_APP_OWNER_ID,
    WsAppHarness,
    connect,
    drain_until_process_completed,
    recv_until_event,
    start_relayed_suggestion,
)

WS_RETRYABLE_HANDSHAKE_STATUS = 503
"""Electron main reconnects with backoff after any 5xx handshake denial, whereas
the auth close codes end its retries (`frontend/electron/ws_reconnect_policy.js`)."""
WS_UNAUTHORIZED_CLOSE_CODE = 4401


def test_ws_auth_header_required(ws_app_harness: WsAppHarness) -> None:
    """Authorizationヘッダー欠如時に 4401 でクローズされることを検証する。"""
    with pytest.raises(WebSocketDisconnect) as closed:
        with ws_app_harness.client.websocket_connect(ORCHESTRATIONS_PATH):
            pytest.fail("a handshake without Authorization was accepted")
    assert closed.value.code == WS_UNAUTHORIZED_CLOSE_CODE


def test_ws_capacity_exceeded_is_retryable_handshake_denial(
    ws_app_harness: WsAppHarness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept前の容量超過はセッションを作らず HTTP 503 で再接続可能にする。"""
    from pantaray_agents.orchestration import router as orchestration_router_module

    monkeypatch.setattr(
        orchestration_router_module,
        "try_acquire_connection",
        lambda *, user_id, limits: False,
    )

    with pytest.raises(WebSocketDenialResponse) as denied:
        with connect(ws_app_harness):
            pytest.fail("a handshake was accepted while capacity was exhausted")

    assert denied.value.status_code == WS_RETRYABLE_HANDSHAKE_STATUS
    assert denied.value.content == b"ws_capacity_exceeded"


def test_ws_session_started_and_stream(ws_app_harness: WsAppHarness) -> None:
    """セッション開始から生成ストリーム受信→resumeで欠損チャンク再送を検証する。"""
    with connect(ws_app_harness) as ws:
        # 1) ハンドシェイク: session_started
        session_id = recv_until_event(ws, "session_started")["data"]["session_id"]

        # 2) 提案生成: process_started → suggestion_chunk … → process_completed
        start_relayed_suggestion(ws_app_harness, user_id=WS_APP_OWNER_ID)
        started = recv_until_event(ws, "process_started")
        process_id = started["data"]["process_id"]

        chunks = drain_until_process_completed(ws)
        assert len(chunks) >= 1

        # 3) セッション再開: last_cursor/last_chunk_index に基づき missing を返し、その後サーバが自動再送
        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": session_id,
                    "last_cursor": chunks[0]["event_id"],  # 厳密検証対象
                    "process_id": process_id,
                    "last_chunk_index": 0,  # 最低限の再開情報
                    "kind": "suggestion",
                },
            }
        )
        resumed = recv_until_event(ws, "session_resumed")
        resumed_from = resumed["data"]["resumed_from_chunk"]
        expected_resent = [c["data"]["content"] for c in chunks][resumed_from:]
        assert len(resumed["data"]["missing_chunks"]) == len(expected_resent)
        for expected in expected_resent:
            # 他イベントが割り込んでもよいので suggestion_chunk だけを拾う
            resent = recv_until_event(ws, "suggestion_chunk", timeout_s=3.0)
            assert resent["data"]["content"] == expected
