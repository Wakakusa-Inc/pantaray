"""The owner and provider account a request reaches, as one comparable value.

A control-socket operation needs the stop barrier exactly when it changes the
effective identity: who owns local data, and which provider account an
LLM or web-search request actually reaches (design 6.2, 6.4, 6.7, 7.3). Rotating
a token inside the same identity is applied without stopping anything, so a
caller compares one value instead of branching per operation.

The model is a per-request setting, not an account boundary. Changing it leaves
in-flight requests alone and the next request reads the new setting.

Nothing here holds a secret. An API key enters only as a SHA-256 fingerprint, so
an identity can be compared, recorded beside a job, and printed in a traceback.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Final, Literal

from .connection_store import (
    ApiKeyProvider,
    ChatGptConnection,
    LlmConnection,
    WebSearchCredential,
    peek_llm_connection,
    peek_web_search_credential,
)
from .identity import logged_out_owner_id
from .session_store import (
    CloudSessionIdentity,
    peek_cloud_session_identity_without_settling,
    read_configured,
)

# Design 6.2 fixes this length: short enough to log, long enough that two keys
# configured on one installation do not collide.
_FINGERPRINT_HEX_DIGITS: Final[int] = 16


@dataclass(frozen=True, slots=True)
class ConnectionIdentity:
    """Which provider account a direct LLM request reaches."""

    kind: Literal["chatgpt", "api_key"]
    # A ChatGPT login also reaches OpenAI; ``kind`` separates the two.
    provider: ApiKeyProvider
    # The ChatGPT ``account_id``, or the API key's fingerprint. A ChatGPT OAuth
    # refresh keeps the same account, so it keeps the same identity (design 6.6).
    fingerprint: str


@dataclass(frozen=True, slots=True)
class WebSearchIdentity:
    """Which search account a direct web-search request reaches."""

    provider: Literal["tavily"]
    fingerprint: str


@dataclass(frozen=True, slots=True)
class EffectiveRouteIdentity:
    """What requests reach right now; each slot's variant is its route.

    A ``CloudSessionIdentity`` means the cloud route, a direct identity means
    the direct route, and ``None`` means ``unconfigured``, so a route change is
    always an identity change as well.
    """

    owner_id: str
    llm: CloudSessionIdentity | ConnectionIdentity | None
    web_search: CloudSessionIdentity | WebSearchIdentity | None


@dataclass(frozen=True, slots=True)
class RouteInputs:
    """The stored values an effective identity is derived from.

    A caller about to apply a control-socket operation reads this once and
    derives both sides of its comparison from the same snapshot, replacing the
    field that operation is about to write. Reading never settles a lapsed
    cloud session, so the identity describes what in-flight work is using and
    the settling itself shows up as a change the barrier has to handle.
    """

    configured: bool
    logged_out_owner_id: str
    cloud: CloudSessionIdentity | None
    llm: ConnectionIdentity | None
    web_search: WebSearchIdentity | None


def _fingerprint(secret: str) -> str:
    return hashlib.sha256(secret.encode("utf-8")).hexdigest()[:_FINGERPRINT_HEX_DIGITS]


def connection_identity(connection: LlmConnection) -> ConnectionIdentity:
    if isinstance(connection, ChatGptConnection):
        return ConnectionIdentity(
            kind="chatgpt",
            provider="openai",
            fingerprint=connection.credential.account_id,
        )
    return ConnectionIdentity(
        kind="api_key",
        provider=connection.provider,
        fingerprint=_fingerprint(connection.api_key),
    )


def web_search_identity(credential: WebSearchCredential) -> WebSearchIdentity:
    return WebSearchIdentity(
        provider=credential.provider,
        fingerprint=_fingerprint(credential.api_key),
    )


def effective_route_identity(inputs: RouteInputs) -> EffectiveRouteIdentity:
    """Resolve the identity from stored values, following 6.4 and 6.7.

    The owner follows ``identity.current_owner_id``: an account owns local data
    while its session is present or expired, otherwise the logged-out owner does.
    """
    owner_id = (
        inputs.logged_out_owner_id if inputs.cloud is None else inputs.cloud.user_id
    )
    if not inputs.configured:
        return EffectiveRouteIdentity(owner_id=owner_id, llm=None, web_search=None)
    if inputs.cloud is not None:
        # An expired session still routes to the cloud, where it fails asking for
        # re-authentication; a stored direct setting never takes over.
        return EffectiveRouteIdentity(
            owner_id=owner_id, llm=inputs.cloud, web_search=inputs.cloud
        )
    return EffectiveRouteIdentity(
        owner_id=owner_id, llm=inputs.llm, web_search=inputs.web_search
    )


def read_route_inputs() -> RouteInputs:
    """Snapshot the current route inputs; the only reads in this module.

    None of these reads changes runtime state.
    """
    connection = peek_llm_connection()
    credential = peek_web_search_credential()
    return RouteInputs(
        configured=read_configured(),
        logged_out_owner_id=logged_out_owner_id(),
        cloud=peek_cloud_session_identity_without_settling(),
        llm=None if connection is None else connection_identity(connection),
        web_search=None if credential is None else web_search_identity(credential),
    )


__all__ = [
    "ConnectionIdentity",
    "EffectiveRouteIdentity",
    "RouteInputs",
    "WebSearchIdentity",
    "connection_identity",
    "effective_route_identity",
    "read_route_inputs",
    "web_search_identity",
]
