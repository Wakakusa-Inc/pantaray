"""The Orchestration WebSockets bound to an owner at handshake time.

A socket answers to the owner it authenticated as, and nothing else revalidates
that binding while the socket is open. When the owner changes, the stop barrier
closes every socket bound to the departing owner from the server side, so the
guarantee does not depend on the client noticing (design 6.3 / 6.10 / 7.3).

The barrier runs on the control socket's own thread and event loop, which is not
the loop that serves the sockets. The ledger therefore records the loop each
socket was accepted on and hands every close back to that loop, which makes
`close_owner_bound_sockets` safe to await from any thread and any loop,
including the serving loop itself.
"""

from __future__ import annotations

import asyncio
import logging
from threading import Lock
from typing import Final

from starlette.websockets import WebSocket, WebSocketDisconnect

logger = logging.getLogger(__name__)

OWNER_CHANGED_CLOSE_CODE: Final[int] = 1001
"""Going Away. Electron main retries this code with backoff and keeps auto-reconnect
enabled, whereas the auth codes (4401 / 4403) disable it for the rest of the process
(`frontend/electron/ws_reconnect_policy.js`). Rebinding to the new owner is not a
rejected credential."""

_CLOSE_HANDSHAKE_TIMEOUT_SECONDS: Final[float] = 1.0
"""Design limit: the close frame is written to a loopback peer, so a reply takes
microseconds. `websockets` would otherwise wait out its 10 second close timeout,
while the control socket operation that owns this barrier must answer main within
5 seconds (design 6.2)."""

_LOCK = Lock()
_SOCKETS_BY_OWNER: dict[str, dict[WebSocket, asyncio.AbstractEventLoop]] = {}


def bind_socket_to_owner(*, owner_id: str, websocket: WebSocket) -> None:
    """Record a socket that passed the handshake, with the loop that serves it."""
    loop = asyncio.get_running_loop()
    with _LOCK:
        _SOCKETS_BY_OWNER.setdefault(owner_id, {})[websocket] = loop


def release_owner_bound_socket(*, owner_id: str, websocket: WebSocket) -> None:
    """Drop a socket from the ledger.

    Idempotent, so every exit path can call it: a handshake that never bound the
    socket, a client that disconnected, and a close this module already sent.
    """
    with _LOCK:
        sockets = _SOCKETS_BY_OWNER.get(owner_id)
        if sockets is None:
            return
        sockets.pop(websocket, None)
        if not sockets:
            del _SOCKETS_BY_OWNER[owner_id]


async def close_owner_bound_sockets(owner_id: str) -> int:
    """Close every socket bound to `owner_id` and return how many were closed.

    Sockets bound to other owners are left alone. Awaitable from the control
    socket thread, from the serving loop, and from any other loop.
    """
    with _LOCK:
        bound = list(_SOCKETS_BY_OWNER.get(owner_id, {}).items())
    if not bound:
        return 0
    closed = await asyncio.gather(
        *(
            # Each close runs on the loop that serves its socket, and is awaited
            # from whichever loop the caller is on.
            asyncio.wrap_future(
                asyncio.run_coroutine_threadsafe(
                    _close(owner_id=owner_id, websocket=websocket), loop
                )
            )
            for websocket, loop in bound
        )
    )
    return sum(closed)


async def _close(*, owner_id: str, websocket: WebSocket) -> bool:
    """Send the close, and release the socket whether or not it arrived."""
    try:
        async with asyncio.timeout(_CLOSE_HANDSHAKE_TIMEOUT_SECONDS):
            await websocket.close(code=OWNER_CHANGED_CLOSE_CODE, reason="owner_changed")
    except (RuntimeError, WebSocketDisconnect) as already_closed:
        # This endpoint already closed the socket (Starlette refuses a second
        # close with RuntimeError) or the peer is gone (uvicorn raises
        # ClientDisconnected, an OSError, which Starlette reports as a 1006
        # disconnect). A socket that is already gone leaves the rest to close.
        logger.info(
            "Owner-bound WS was already closed: owner_id=%s error=%s",
            owner_id,
            already_closed,
        )
        return False
    except TimeoutError:
        # The endpoint is already fenced: Starlette marks the socket disconnected
        # before it writes the frame, so it can no longer read or write. Only the
        # peer's half of the close handshake is outstanding.
        logger.warning(
            "Owner-bound WS did not complete its close handshake: owner_id=%s",
            owner_id,
        )
    finally:
        release_owner_bound_socket(owner_id=owner_id, websocket=websocket)
    return True


__all__ = [
    "OWNER_CHANGED_CLOSE_CODE",
    "bind_socket_to_owner",
    "close_owner_bound_sockets",
    "release_owner_bound_socket",
]
