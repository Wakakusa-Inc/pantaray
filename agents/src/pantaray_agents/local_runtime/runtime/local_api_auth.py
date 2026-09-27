from __future__ import annotations

import hmac
import secrets
from threading import Lock
from typing import Final

from pantaray_agents.auth_http import authentication_failed_exception
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .identity import current_owner_id

LOCAL_API_TOKEN_BYTES: Final[int] = 32

_TOKEN_LOCK = Lock()
_LOCAL_API_TOKEN: str | None = None


class LocalApiTokenUnavailableError(MigrationError):
    """Raised when the runtime has not issued a local API token."""


def issue_local_api_token() -> None:
    """Mint the token for this runtime lifetime; it is never persisted or logged."""
    global _LOCAL_API_TOKEN
    with _TOKEN_LOCK:
        _LOCAL_API_TOKEN = secrets.token_urlsafe(LOCAL_API_TOKEN_BYTES)


def clear_local_api_token() -> None:
    global _LOCAL_API_TOKEN
    with _TOKEN_LOCK:
        _LOCAL_API_TOKEN = None


def read_local_api_token() -> str:
    """Return the token itself; only the control socket may hand it to Electron main."""
    with _TOKEN_LOCK:
        token = _LOCAL_API_TOKEN
    if token is None:
        raise LocalApiTokenUnavailableError(
            "local runtime has not issued a local API token"
        )
    return token


def local_api_token_matches(presented: str) -> bool:
    # Header values decode as latin-1, so compare bytes: compare_digest rejects
    # non-ASCII str input with TypeError instead of reporting a mismatch.
    return hmac.compare_digest(
        presented.encode("utf-8"), read_local_api_token().encode("utf-8")
    )


async def authenticate_local_api_request(token: str | None) -> str:
    """Resolve a local HTTP request to the current owner, or reject it."""
    if not token or not local_api_token_matches(token):
        raise authentication_failed_exception()
    return current_owner_id()


__all__ = [
    "LOCAL_API_TOKEN_BYTES",
    "LocalApiTokenUnavailableError",
    "authenticate_local_api_request",
    "clear_local_api_token",
    "issue_local_api_token",
    "local_api_token_matches",
    "read_local_api_token",
]
