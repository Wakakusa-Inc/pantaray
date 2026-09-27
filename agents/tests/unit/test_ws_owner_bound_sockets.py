from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Iterator
from types import ModuleType

import pytest
from starlette.testclient import (
    TestClient,
    WebSocketDenialResponse,
    WebSocketTestSession,
)
from starlette.websockets import WebSocket, WebSocketDisconnect

from pantaray_agents.local_runtime.runtime.admission import admission_closed
from pantaray_agents.local_runtime.runtime.identity import register_logged_out_owner
from pantaray_agents.orchestration import router
from pantaray_agents.orchestration.ws.capacity import WSCapacityLimits
from pantaray_agents.orchestration.ws.owner_bound_sockets import (
    bind_socket_to_owner,
    close_owner_bound_sockets,
)

from .test_local_auth_lifecycle import (
    INVALID_TOKEN,
    ISSUED_TOKEN,
    LOCAL_OWNER_ID,
    authorization,
)
from .test_local_auth_lifecycle import local_app_module as local_app_module

OTHER_OWNER_ID = "local-owner-2"
CLOSE_WAIT_SECONDS = 5.0
GOING_AWAY_CLOSE_CODE = 1001
"""Electron main retries this code and keeps auto-reconnect enabled; anything outside
its retryable set ends the retries for good (`frontend/electron/ws_reconnect_policy.js`)."""
TRY_AGAIN_LATER_CLOSE_CODE = 1013
"""Also retried, and unlike 4401 / 4403 it leaves auto-reconnect on (same file)."""
RETRYABLE_DENIAL_STATUS = 503
"""A handshake denied before accept: main reconnects after any 5xx (same file)."""
CLOSE_ADMISSION = "admission_closed"
SWAP_THE_OWNER = "owner_changed"


@pytest.fixture
def ws_client(
    monkeypatch: pytest.MonkeyPatch, local_app_module: ModuleType
) -> Iterator[TestClient]:
    """A client that can hold the several sockets an owner change has to close."""
    monkeypatch.setattr(
        router.WSOrchestrationHandler, "start_suggestion_relay", lambda self: None
    )
    monkeypatch.setattr(
        router,
        "load_ws_capacity_limits",
        lambda: WSCapacityLimits(
            max_connections_total=8,
            max_connections_per_user=8,
        ),
    )
    with TestClient(local_app_module.create_local_app()) as client:
        yield client


@contextlib.contextmanager
def owner_socket(client: TestClient, owner_id: str) -> Iterator[WebSocketTestSession]:
    """Open a socket whose handshake binds it to `owner_id`."""
    register_logged_out_owner(owner_id)
    with client.websocket_connect(
        f"/v1/agents/users/{owner_id}/orchestrations",
        headers=authorization(ISSUED_TOKEN),
    ) as websocket:
        assert websocket.receive_json()["event"] == "session_started"
        yield websocket


def close_from_control_socket_thread(owner_id: str) -> int:
    """Close the way the stop barrier will: another thread, another event loop."""
    closed: list[int] = []
    thread = threading.Thread(
        target=lambda: closed.append(asyncio.run(close_owner_bound_sockets(owner_id))),
        name="control-socket-stub",
    )
    thread.start()
    thread.join(timeout=CLOSE_WAIT_SECONDS)
    assert not thread.is_alive(), "closing owner-bound sockets did not finish"
    return closed[0]


def close_on_serving_loop(client: TestClient, owner_id: str) -> int:
    """Close from the very loop that serves the sockets; this must not deadlock."""
    assert client.portal is not None
    return client.portal.start_task_soon(close_owner_bound_sockets, owner_id).result(
        timeout=CLOSE_WAIT_SECONDS
    )


def assert_closed_by_owner_change(websocket: WebSocketTestSession) -> None:
    with pytest.raises(WebSocketDisconnect) as closed:
        websocket.receive_json()
    assert closed.value.code == GOING_AWAY_CLOSE_CODE


def assert_still_usable(websocket: WebSocketTestSession) -> None:
    websocket.send_text("not json")
    assert websocket.receive_json()["event"] == "error"


def test_an_owner_change_closes_that_owners_sockets_and_leaves_the_others(
    ws_client: TestClient,
) -> None:
    with (
        owner_socket(ws_client, LOCAL_OWNER_ID) as first,
        owner_socket(ws_client, LOCAL_OWNER_ID) as second,
        owner_socket(ws_client, OTHER_OWNER_ID) as other,
    ):
        assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 2

        assert_closed_by_owner_change(first)
        assert_closed_by_owner_change(second)
        assert_still_usable(other)


def test_sockets_can_be_closed_from_the_loop_that_serves_them(
    ws_client: TestClient,
) -> None:
    with owner_socket(ws_client, LOCAL_OWNER_ID) as websocket:
        assert close_on_serving_loop(ws_client, LOCAL_OWNER_ID) == 1

        assert_closed_by_owner_change(websocket)


def test_a_socket_the_client_closed_is_no_longer_in_the_ledger(
    ws_client: TestClient,
) -> None:
    with owner_socket(ws_client, LOCAL_OWNER_ID):
        pass

    assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 0


def test_a_socket_this_barrier_closed_is_no_longer_in_the_ledger(
    ws_client: TestClient,
) -> None:
    with owner_socket(ws_client, LOCAL_OWNER_ID):
        assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 1

        assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 0


def test_a_handshake_while_admission_is_closed_is_denied_retryably(
    ws_client: TestClient,
) -> None:
    """A barrier in flight is exactly when the owner reads as someone else, so
    this is refused before the owner check: 4403 would end main's reconnects for
    good, while a denial response sends it back after a backoff."""
    register_logged_out_owner(LOCAL_OWNER_ID)

    with admission_closed():
        with pytest.raises(WebSocketDenialResponse) as denied:
            with ws_client.websocket_connect(
                f"/v1/agents/users/{LOCAL_OWNER_ID}/orchestrations",
                headers=authorization(ISSUED_TOKEN),
            ):
                pytest.fail("a handshake was accepted while admission was closed")

    assert denied.value.status_code == RETRYABLE_DENIAL_STATUS
    assert denied.value.content == b"ws_admission_closed"
    assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 0


@contextlib.contextmanager
def barrier_landing_after_the_bind(
    monkeypatch: pytest.MonkeyPatch, *, effect: str
) -> Iterator[None]:
    """Run one of the barrier's visible effects in the window the recheck covers.

    The endpoint awaits `accept()` between its own admission check and the bind,
    so the barrier can land in between. Binding first and rechecking after is
    what keeps such a socket from outliving the owner it bound to.
    """
    with contextlib.ExitStack() as barrier:

        def bind_then_run_the_barrier(*, owner_id: str, websocket: WebSocket) -> None:
            bind_socket_to_owner(owner_id=owner_id, websocket=websocket)
            if effect == CLOSE_ADMISSION:
                barrier.enter_context(admission_closed())
            else:
                register_logged_out_owner(OTHER_OWNER_ID)

        monkeypatch.setattr(router, "bind_socket_to_owner", bind_then_run_the_barrier)
        yield


@pytest.mark.parametrize("effect", [CLOSE_ADMISSION, SWAP_THE_OWNER])
def test_a_handshake_the_barrier_overtakes_after_binding_closes_itself(
    ws_client: TestClient, monkeypatch: pytest.MonkeyPatch, effect: str
) -> None:
    """Either half of the recheck is enough on its own: a barrier that has only
    closed admission, and one that has already swapped the owner."""
    register_logged_out_owner(LOCAL_OWNER_ID)

    with barrier_landing_after_the_bind(monkeypatch, effect=effect):
        with pytest.raises(WebSocketDisconnect) as closed:
            with ws_client.websocket_connect(
                f"/v1/agents/users/{LOCAL_OWNER_ID}/orchestrations",
                headers=authorization(ISSUED_TOKEN),
            ) as websocket:
                websocket.receive_json()

    assert closed.value.code == TRY_AGAIN_LATER_CLOSE_CODE
    assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 0


@pytest.mark.parametrize(
    ("token_kind", "path_owner_id"),
    [(INVALID_TOKEN, LOCAL_OWNER_ID), (ISSUED_TOKEN, OTHER_OWNER_ID)],
)
def test_a_rejected_handshake_binds_no_socket(
    ws_client: TestClient, token_kind: str, path_owner_id: str
) -> None:
    register_logged_out_owner(LOCAL_OWNER_ID)
    with pytest.raises(WebSocketDisconnect):
        with ws_client.websocket_connect(
            f"/v1/agents/users/{path_owner_id}/orchestrations",
            headers=authorization(token_kind),
        ):
            pytest.fail("a rejected handshake accepted a connection")

    assert close_from_control_socket_thread(LOCAL_OWNER_ID) == 0
    assert close_from_control_socket_thread(OTHER_OWNER_ID) == 0
