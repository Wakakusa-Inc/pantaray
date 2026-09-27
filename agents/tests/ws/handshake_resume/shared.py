"""Shared setup for the WS handshake / resume suite.

The app harness, its mock Suggestion repository, the relay seed and the
timeout-bounded receive helper all belong to
`tests/integration/ws_orchestration_test_helpers.py`. This suite reuses them so
there is one WS app harness to keep current -- a second copy is what let this
suite drift past the local API token and owner-bound handshake contracts. Only
the receive-until helper the resume assertions need lives here.
"""

from __future__ import annotations

import time

from starlette.testclient import WebSocketTestSession
from tests.integration.ws_orchestration_test_helpers import (
    WS_APP_OWNER_ID,
    WsAppHarness,
    _receive_ws_json,
    _ws_connect,
    start_relayed_suggestion,
    ws_app_harness,
)

__all__ = [
    "ORCHESTRATIONS_PATH",
    "WS_APP_OWNER_ID",
    "WsAppHarness",
    "connect",
    "recv",
    "recv_until_event",
    "start_relayed_suggestion",
    "ws_app_harness",
]

ORCHESTRATIONS_PATH = f"/v1/agents/users/{WS_APP_OWNER_ID}/orchestrations"

connect = _ws_connect


def recv(ws: WebSocketTestSession, *, timeout_s: float = 2.0) -> dict[str, object]:
    """Receive one WS message, failing fast instead of hanging on a missing event."""
    return _receive_ws_json(ws, timeout_s=timeout_s)


def recv_until_event(
    ws: WebSocketTestSession, event: str, *, timeout_s: float = 5.0
) -> dict[str, object]:
    """Receive until `event` arrives, reporting what did arrive on a timeout."""
    deadline = time.time() + timeout_s
    seen: list[str] = []
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise AssertionError(f"Timed out waiting for event={event}. Seen={seen}")
        try:
            message = recv(ws, timeout_s=remaining)
        except TimeoutError:
            raise AssertionError(
                f"Timed out waiting for event={event}. Seen={seen}"
            ) from None
        seen.append(str(message.get("event")))
        if message.get("event") == event:
            return message


def drain_until_process_completed(
    ws: WebSocketTestSession, *, timeout_s: float = 10.0
) -> list[dict[str, object]]:
    """Collect the suggestion chunks of one relayed process up to its completion."""
    chunks: list[dict[str, object]] = []
    deadline = time.time() + timeout_s
    while True:
        remaining = deadline - time.time()
        if remaining <= 0:
            raise AssertionError("Timed out waiting for process_completed")
        message = recv(ws, timeout_s=remaining)
        if message.get("event") == "suggestion_chunk":
            chunks.append(message)
        elif message.get("event") == "process_completed":
            return chunks
