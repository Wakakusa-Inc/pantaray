"""Direct provider connection settings held in the runtime process memory.

Electron main owns the durable copy of these settings (design 6.1) and resends
them through ``configure`` after every runtime restart, so nothing here is
persisted and nothing here is ever written to a log, an error message, or a
``status`` response.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime
from threading import Lock
from typing import Final, Literal, cast

from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .control_payload import require_payload_object, require_string_field
from .session_store import (
    AUTH_CONTEXT_EXPIRED_STATE,
    AUTH_CONTEXT_PRESENT_STATE,
    read_auth_context_state,
    read_configured,
)

type ConnectionRoute = Literal["cloud", "direct", "unconfigured"]
# Providers reached with a bare API key on their own default endpoint.
type ApiKeyProvider = Literal["openai", "fireworks", "anthropic"]

_API_KEY_PROVIDERS: Final[tuple[str, ...]] = (
    "openai",
    "fireworks",
    "anthropic",
)


@dataclass(frozen=True, slots=True)
class ChatGptCredential:
    """A ChatGPT OAuth token; main keeps the refresh token to itself (6.6)."""

    access_token: str
    expires_at: str
    account_id: str


@dataclass(frozen=True, slots=True)
class ChatGptConnection:
    model: str
    credential: ChatGptCredential
    kind: Literal["chatgpt"] = "chatgpt"


@dataclass(frozen=True, slots=True)
class ApiKeyConnection:
    provider: ApiKeyProvider
    model: str
    api_key: str
    kind: Literal["api_key"] = "api_key"


type LlmConnection = ChatGptConnection | ApiKeyConnection


@dataclass(frozen=True, slots=True)
class WebSearchCredential:
    api_key: str
    provider: Literal["tavily"] = "tavily"


_CONNECTION_LOCK = Lock()
_LLM_CONNECTION: LlmConnection | None = None
_WEB_SEARCH_CREDENTIAL: WebSearchCredential | None = None
_UNBOUND_REQUEST_CONNECTION = object()
_REQUEST_LLM_CONNECTION: ContextVar[object] = ContextVar(
    "request_llm_connection", default=_UNBOUND_REQUEST_CONNECTION
)


def _read_chatgpt_connection(
    payload: dict[str, object], *, model: str
) -> ChatGptConnection:
    credential = require_payload_object(payload, field_name="credential")
    return ChatGptConnection(
        model=model,
        credential=ChatGptCredential(
            access_token=require_string_field(credential, "access_token"),
            expires_at=require_string_field(credential, "expires_at"),
            account_id=require_string_field(credential, "account_id"),
        ),
    )


def _read_api_key_connection(
    payload: dict[str, object], *, model: str
) -> ApiKeyConnection:
    provider = require_string_field(payload, "provider")
    api_key = require_string_field(payload, "api_key")
    if provider not in _API_KEY_PROVIDERS:
        raise MigrationError(
            "llm_connection.provider must be one of openai, anthropic, fireworks"
        )
    return ApiKeyConnection(
        provider=cast(ApiKeyProvider, provider), model=model, api_key=api_key
    )


def read_llm_connection(payload: dict[str, object]) -> LlmConnection:
    """Build a connection from an untrusted control payload.

    A rejection never quotes a field value: a caller that puts a secret in the
    wrong field must not read it back out of the error.
    """
    kind = require_string_field(payload, "kind")
    model = require_string_field(payload, "model")
    if kind == "chatgpt":
        return _read_chatgpt_connection(payload, model=model)
    if kind == "api_key":
        return _read_api_key_connection(payload, model=model)
    raise MigrationError("llm_connection.kind must be chatgpt or api_key")


def read_web_search_credential(payload: dict[str, object]) -> WebSearchCredential:
    if require_string_field(payload, "provider") != "tavily":
        raise MigrationError("web_search_credential.provider must be tavily")
    return WebSearchCredential(api_key=require_string_field(payload, "api_key"))


def read_optional_llm_connection(payload: dict[str, object]) -> LlmConnection | None:
    if payload.get("llm_connection") is None:
        return None
    return read_llm_connection(
        require_payload_object(payload, field_name="llm_connection")
    )


def read_optional_web_search_credential(
    payload: dict[str, object],
) -> WebSearchCredential | None:
    if payload.get("web_search_credential") is None:
        return None
    return read_web_search_credential(
        require_payload_object(payload, field_name="web_search_credential")
    )


def apply_connection_configuration(
    *,
    llm_connection: LlmConnection | None,
    web_search_credential: WebSearchCredential | None,
) -> None:
    """Replace both connection settings at once (``configure``, design 6.2)."""
    global _LLM_CONNECTION, _WEB_SEARCH_CREDENTIAL
    with _CONNECTION_LOCK:
        _LLM_CONNECTION = llm_connection
        _WEB_SEARCH_CREDENTIAL = web_search_credential


def set_llm_connection(connection: LlmConnection) -> None:
    global _LLM_CONNECTION
    with _CONNECTION_LOCK:
        _LLM_CONNECTION = connection


def clear_llm_connection() -> None:
    global _LLM_CONNECTION
    with _CONNECTION_LOCK:
        _LLM_CONNECTION = None


def set_web_search_credential(credential: WebSearchCredential) -> None:
    global _WEB_SEARCH_CREDENTIAL
    with _CONNECTION_LOCK:
        _WEB_SEARCH_CREDENTIAL = credential


def clear_web_search_credential() -> None:
    global _WEB_SEARCH_CREDENTIAL
    with _CONNECTION_LOCK:
        _WEB_SEARCH_CREDENTIAL = None


def peek_llm_connection() -> LlmConnection | None:
    with _CONNECTION_LOCK:
        return _LLM_CONNECTION


@contextmanager
def bind_request_llm_connection(connection: LlmConnection | None) -> Iterator[None]:
    """Keep a prepared Action turn and its provider send on one connection."""
    token = _REQUEST_LLM_CONNECTION.set(connection)
    try:
        yield
    finally:
        _REQUEST_LLM_CONNECTION.reset(token)


def request_llm_connection() -> LlmConnection | None:
    connection = _REQUEST_LLM_CONNECTION.get()
    if connection is _UNBOUND_REQUEST_CONNECTION:
        return peek_llm_connection()
    return cast(LlmConnection | None, connection)


def peek_web_search_credential() -> WebSearchCredential | None:
    with _CONNECTION_LOCK:
        return _WEB_SEARCH_CREDENTIAL


def reset_connection_store() -> None:
    global _LLM_CONNECTION, _WEB_SEARCH_CREDENTIAL
    with _CONNECTION_LOCK:
        _LLM_CONNECTION = None
        _WEB_SEARCH_CREDENTIAL = None


def llm_connection_can_send(connection: LlmConnection) -> bool:
    """Whether a request could really be sent on this connection right now.

    Only a ChatGPT token has a lifetime the runtime can read. Electron main
    renews it five minutes ahead of that expiry (design 6.6), so one that has
    lapsed means the renewal has not landed yet. That leaves the direct route
    in the same shape as an expired cloud session: every request is refused
    before it is sent, and it recovers on its own or with a new sign-in. The
    route stays ``direct`` -- only the sending stops.

    An API key has no readable lifetime. A wrong one is rejected by the
    provider and only the user can fix it, so it never stops sending here.
    """

    if not isinstance(connection, ChatGptConnection):
        return True
    try:
        return datetime.now(UTC) < datetime.fromisoformat(
            connection.credential.expires_at
        )
    except (TypeError, ValueError):
        # A lifetime that cannot be compared is not one to send a token on.
        return False


def _route(*, has_direct_setting: bool) -> ConnectionRoute:
    """Resolve the effective route from the cloud session and the setting.

    ``read_auth_context_state`` settles an elapsed session into ``expired``
    first, so a lapsed token never resolves as ``present``. An expired session
    still routes to the cloud, where the call fails asking for re-authentication
    (design 6.4 step 3 and 6.7 step 3); it never falls back to a direct
    connection.
    """
    if not read_configured():
        return "unconfigured"
    if read_auth_context_state() in (
        AUTH_CONTEXT_PRESENT_STATE,
        AUTH_CONTEXT_EXPIRED_STATE,
    ):
        return "cloud"
    return "direct" if has_direct_setting else "unconfigured"


def read_llm_route() -> ConnectionRoute:
    return _route(has_direct_setting=peek_llm_connection() is not None)


def read_web_search_route() -> ConnectionRoute:
    return _route(has_direct_setting=peek_web_search_credential() is not None)


__all__ = [
    "ApiKeyConnection",
    "ChatGptConnection",
    "ChatGptCredential",
    "ConnectionRoute",
    "LlmConnection",
    "WebSearchCredential",
    "apply_connection_configuration",
    "bind_request_llm_connection",
    "clear_llm_connection",
    "clear_web_search_credential",
    "llm_connection_can_send",
    "peek_llm_connection",
    "peek_web_search_credential",
    "read_llm_connection",
    "read_llm_route",
    "read_optional_llm_connection",
    "read_optional_web_search_credential",
    "request_llm_connection",
    "read_web_search_credential",
    "read_web_search_route",
    "reset_connection_store",
    "set_llm_connection",
    "set_web_search_credential",
]
