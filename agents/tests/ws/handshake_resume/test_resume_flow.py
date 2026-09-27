from pantaray_agents.local_runtime.runtime.identity import register_logged_out_owner

from .shared import (
    WS_APP_OWNER_ID,
    WsAppHarness,
    connect,
    drain_until_process_completed,
    recv,
    recv_until_event,
    start_relayed_suggestion,
)

UNKNOWN_CURSOR = "00000000-0000-0000-0000-000000000000"
OTHER_OWNER_ID = "local-owner-2"


def test_ws_resume_invalid_cursor_process_mismatch(ws_app_harness: WsAppHarness):
    """process_id不一致によりlast_cursor検証が失敗しエラーが返ることを検証する。"""
    with connect(ws_app_harness) as ws:
        session_id = recv_until_event(ws, "session_started")["data"]["session_id"]

        start_relayed_suggestion(ws_app_harness, user_id=WS_APP_OWNER_ID)
        recv_until_event(ws, "process_started")
        chunks = drain_until_process_completed(ws)
        assert len(chunks) >= 1

        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": session_id,
                    "last_cursor": chunks[0]["event_id"],
                    "process_id": "other-proc",
                    "last_chunk_index": 0,
                    "kind": "suggestion",
                },
            }
        )
        err = recv_until_event(ws, "error")
        assert err["data"]["error_code"] == "WS_RESUME_INVALID_CURSOR"


def test_ws_resume_session_expired(ws_app_harness: WsAppHarness):
    """期限切れセッションでresume_sessionするとsession_expiredが返ることを検証する。"""
    from pantaray_agents.orchestration import router as orch_router

    with connect(ws_app_harness) as ws:
        session_id = recv_until_event(ws, "session_started")["data"]["session_id"]

        # セッションを期限切れにする（expiry は最終activity基準）
        session_record = orch_router.SESSION_STORE.get(session_id)
        assert session_record is not None
        session_record.created_at = 0
        session_record.last_seen_at = 0

        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": session_id,
                    "last_cursor": UNKNOWN_CURSOR,
                    "process_id": "any-proc",
                    "last_chunk_index": 0,
                    "kind": "suggestion",
                },
            }
        )
        assert recv_until_event(ws, "session_expired")


def test_ws_resume_unknown_process_resumes_with_no_missing_chunks(
    ws_app_harness: WsAppHarness,
):
    """未知のprocess_id指定時に安全に再開点が計算され、欠損無しで再開されることを検証する。"""
    with connect(ws_app_harness) as ws:
        session_id = recv_until_event(ws, "session_started")["data"]["session_id"]

        ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": session_id,
                    "last_cursor": UNKNOWN_CURSOR,
                    "process_id": "unknown-proc",
                    "last_chunk_index": 2,
                    "kind": "suggestion",
                },
            }
        )
        resumed = recv_until_event(ws, "session_resumed")
        assert resumed["data"]["resumed_from_chunk"] == 3
        assert resumed["data"]["missing_chunks"] == []


def test_ws_resume_of_a_previous_owners_session_is_rejected(
    ws_app_harness: WsAppHarness,
):
    """所有者が入れ替わったあと、前の所有者の session_id での resume は拒否される。

    Handshake が socket を現在の所有者に束縛しても、`SESSION_STORE` はプロセス内に
    残り続けるため、サインアウト前の session_id を握ったままの client が
    再接続してくる経路は実在する。
    """
    with connect(ws_app_harness) as previous_owner_ws:
        previous_session_id = recv_until_event(previous_owner_ws, "session_started")[
            "data"
        ]["session_id"]

    register_logged_out_owner(OTHER_OWNER_ID)
    with connect(ws_app_harness, user_id=OTHER_OWNER_ID) as current_owner_ws:
        recv_until_event(current_owner_ws, "session_started")
        current_owner_ws.send_json(
            {
                "event": "resume_session",
                "data": {
                    "session_id": previous_session_id,
                    "last_cursor": UNKNOWN_CURSOR,
                    "process_id": "any-proc",
                    "last_chunk_index": 0,
                    "kind": "suggestion",
                },
            }
        )
        assert recv_until_event(current_owner_ws, "session_expired")


def test_ws_ack_event_session_id_mismatch_is_ignored(ws_app_harness: WsAppHarness):
    """ACK_EVENT で session_id を偽装しても、当該接続セッション以外はACKされないことを検証する。"""
    from pantaray_agents.orchestration import router as orch_router

    with connect(ws_app_harness) as ws:
        session_id = recv_until_event(ws, "session_started")["data"]["session_id"]

        start_relayed_suggestion(ws_app_harness, user_id=WS_APP_OWNER_ID)
        started = recv_until_event(ws, "process_started")
        process_id = started["data"]["process_id"]
        event_id = started["event_id"]

        # session_id を偽装したACKは無視される
        ws.send_json(
            {
                "event": "ack_event",
                "data": {
                    "session_id": "other-session",
                    "process_id": process_id,
                    "event_id": event_id,
                },
            }
        )
        # ACKはレスポンスを返さないため、次のイベントを1つ読むことでサーバ側処理を進める
        recv_until_event(ws, "suggestion_chunk")
        session_record = orch_router.SESSION_STORE.get(session_id)
        assert session_record is not None
        assert session_record.events.get(event_id, {}).get("acked") is False

        # 正しいsession_idでACKすると反映される
        ws.send_json(
            {
                "event": "ack_event",
                "data": {
                    "session_id": session_id,
                    "process_id": process_id,
                    "event_id": event_id,
                },
            }
        )
        recv_until_event(ws, "process_completed")
        assert session_record.events.get(event_id, {}).get("acked") is True


def test_ws_invalid_json_yields_error(ws_app_harness: WsAppHarness):
    """不正なJSON文字列送信時にWS_INVALID_JSONエラーが返ることを検証する。"""
    with connect(ws_app_harness) as ws:
        recv_until_event(ws, "session_started")
        ws.send_text("not-a-json")
        err = recv(ws)
        assert err["event"] == "error"
        assert err["data"]["error_code"] == "WS_INVALID_JSON"
