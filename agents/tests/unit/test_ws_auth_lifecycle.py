from __future__ import annotations

from types import ModuleType
from typing import Never

import pytest
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from pantaray_agents.orchestration import router

from .test_local_auth_lifecycle import (
    INVALID_TOKEN,
    ISSUED_TOKEN,
    LOCAL_OWNER_ID,
    MISSING_TOKEN,
    authorization,
)
from .test_local_auth_lifecycle import local_app_module as local_app_module


@pytest.mark.parametrize(
    ("token_kind", "path_user_id", "expected"),
    [
        (MISSING_TOKEN, LOCAL_OWNER_ID, 4401),
        (INVALID_TOKEN, LOCAL_OWNER_ID, 4401),
        (ISSUED_TOKEN, "another-owner", 4403),
    ],
)
def test_ws_authentication_finishes_before_reserving_capacity_or_creating_session(
    monkeypatch: pytest.MonkeyPatch,
    local_app_module: ModuleType,
    token_kind: str,
    path_user_id: str,
    expected: int,
) -> None:
    def forbidden(*args: object, **kwargs: object) -> Never:
        raise AssertionError("failed authentication reached session admission")

    monkeypatch.setattr(router, "try_acquire_connection", forbidden)
    monkeypatch.setattr(router.SESSION_STORE, "create_session", forbidden)
    path = f"/v1/agents/users/{path_user_id}/orchestrations"
    with TestClient(local_app_module.create_local_app()) as client:
        with pytest.raises(WebSocketDisconnect) as rejection:
            with client.websocket_connect(path, headers=authorization(token_kind)):
                pytest.fail("failed authentication accepted a connection")
        assert rejection.value.code == expected


def test_ws_accepts_the_issued_token_for_the_current_owner(
    monkeypatch: pytest.MonkeyPatch,
    local_app_module: ModuleType,
) -> None:
    monkeypatch.setattr(
        router.WSOrchestrationHandler, "start_suggestion_relay", lambda self: None
    )
    path = f"/v1/agents/users/{LOCAL_OWNER_ID}/orchestrations"
    with TestClient(local_app_module.create_local_app()) as client:
        with client.websocket_connect(
            path, headers=authorization(ISSUED_TOKEN)
        ) as websocket:
            assert websocket.receive_json()["event"] == "session_started"
