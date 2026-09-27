from __future__ import annotations

import sqlite3
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from pantaray_agents.agents.core import PublicAgentHTTPError
from pantaray_agents.local_runtime.action_conversation import cursor_codec as cursor
from pantaray_agents.local_runtime.runtime import runtime_env
from pantaray_agents.local_runtime.storage import migrations
from pantaray_agents.local_runtime.storage import sqlite_vector as vector
from pantaray_agents.routers import history as history_router
from pantaray_agents.schema import conversation_history as history

_PAGE = history.ConversationHistoryPage(
    items=(
        history.ConversationHistoryItem(
            kind="conversation",
            action_id="action-1",
            title="USER request",
            updated_at="2026-08-30T00:00:00.000Z",
            status="idle",
            latest_completion_event_id="event-1",
        ),
    ),
    next_cursor="next-page",
)
_PATH = "/api/agent/history"
_READER = "read_conversation_history_page_in_connection"


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(history_router.router)
    app.dependency_overrides[history_router.get_current_user_id_from_token] = lambda: (
        "user-123"
    )
    return TestClient(app)


def test_history_reads_configured_snapshot_and_returns_strict_page(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requests: list[tuple[object, ...]] = []

    def read_page(**kwargs: object) -> history.ConversationHistoryPage:
        connection = kwargs["connection"]
        assert isinstance(connection, sqlite3.Connection)
        assert connection.in_transaction
        assert connection.row_factory is sqlite3.Row
        assert connection.execute("PRAGMA busy_timeout").fetchone()[0] == 1_500
        assert (
            connection.execute(
                "SELECT pantaray_conversation_history_casefold(?)", ("CAFÉ",)
            ).fetchone()[0]
            == "café"
        )
        requests.append(
            (
                kwargs["user_id"],
                kwargs["cursor"],
                kwargs["limit"],
                kwargs["status"],
                kwargs["search_text"],
            )
        )
        return _PAGE

    monkeypatch.setenv("LOCAL_DB_PATH", ":memory:")
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", "1500")
    monkeypatch.setattr(history_router, _READER, read_page)

    with _client() as client:
        default_response = client.get(_PATH, headers={"Authorization": "Bearer token"})
        emoji_response = client.get(
            _PATH,
            params={
                "cursor": "cursor-1",
                "limit": 100,
                "status": "idle",
                "search_text": "😀" * 256,
            },
            headers={"Authorization": "Bearer token"},
        )

    assert default_response.json() == _PAGE.model_dump(mode="json")
    assert emoji_response.status_code == 200
    assert requests == [
        ("user-123", None, 25, "all", ""),
        ("user-123", "cursor-1", 100, "idle", "😀" * 256),
    ]


def test_history_rejects_invalid_query_before_database(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_config = Mock(side_effect=AssertionError("database must not be opened"))
    monkeypatch.setattr(runtime_env, "read_local_runtime_db_config", read_config)

    with _client() as client:
        for params in (
            {"search_text": "😀" * 257},
            {"limit": 0},
            {"limit": 101},
            {"status": "pending"},
        ):
            response = client.get(
                _PATH,
                params=params,
                headers={"Authorization": "Bearer token"},
            )
            assert response.status_code == 422
    read_config.assert_not_called()


@pytest.mark.parametrize(
    ("error", "expected_status", "boundary"),
    [
        (cursor.OpaqueCursorError("private cursor"), 422, _READER),
        (migrations.MigrationError("private migration"), 500, _READER),
        (sqlite3.DatabaseError("private database"), 500, _READER),
        (
            vector.SQLiteVectorExtensionError("private vector"),
            500,
            "configure_connection",
        ),
    ],
)
def test_history_maps_fixed_public_failures(
    monkeypatch: pytest.MonkeyPatch,
    error: Exception,
    expected_status: int,
    boundary: str,
) -> None:
    monkeypatch.setenv("LOCAL_DB_PATH", ":memory:")
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", "1500")
    monkeypatch.setattr(history_router, boundary, Mock(side_effect=error))

    with pytest.raises((HTTPException, PublicAgentHTTPError)) as exc_info:
        history_router.list_conversation_history(
            cursor=None,
            limit=25,
            status_filter="all",
            search_text="",
            user_id="user-123",
        )
    mapped = exc_info.value
    assert mapped.status_code == expected_status
    assert "private" not in str(mapped)
    if isinstance(mapped, PublicAgentHTTPError):
        assert mapped.error_code == "CONVERSATION_HISTORY_INTEGRITY_ERROR"
        assert mapped.public_message is None
