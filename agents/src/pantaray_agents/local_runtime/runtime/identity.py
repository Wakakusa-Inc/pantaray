from __future__ import annotations

from threading import Lock

from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .session_store import (
    peek_active_desktop_session,
    peek_expired_cloud_identity,
)

_OWNER_LOCK = Lock()
_LOGGED_OUT_OWNER_ID: str | None = None


class OwnerMismatchError(MigrationError):
    """Raised when an owner-scoped record belongs to someone else."""


class LocalOwnerUnavailableError(MigrationError):
    """Raised when the logged-out owner has not been registered by startup."""


def register_logged_out_owner(user_id: str) -> None:
    global _LOGGED_OUT_OWNER_ID
    normalized = _require_non_empty(user_id, field_name="user_id")
    with _OWNER_LOCK:
        _LOGGED_OUT_OWNER_ID = normalized


def reset_logged_out_owner() -> None:
    global _LOGGED_OUT_OWNER_ID
    with _OWNER_LOCK:
        _LOGGED_OUT_OWNER_ID = None


def logged_out_owner_id() -> str:
    with _OWNER_LOCK:
        owner_id = _LOGGED_OUT_OWNER_ID
    if owner_id is None:
        raise LocalOwnerUnavailableError(
            "local runtime has not registered the logged-out owner"
        )
    return owner_id


def current_owner_id() -> str:
    """The owner of local data right now: the signed-in account, else the logged-out owner."""
    active_session = peek_active_desktop_session()
    if active_session is not None:
        return active_session.user_id
    expired_identity = peek_expired_cloud_identity()
    if expired_identity is not None:
        # An expired session keeps showing the account's data; only cloud calls fail.
        return expired_identity.user_id
    return logged_out_owner_id()


def verify_current_owner(owner_user_id: str) -> None:
    """Reject work owned by anyone but the current owner (design 6.10)."""
    normalized_owner_user_id = _require_non_empty(
        owner_user_id,
        field_name="owner_user_id",
    )
    if current_owner_id() != normalized_owner_user_id:
        raise OwnerMismatchError("owner_user_id does not match the current owner")


def _require_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MigrationError(f"{field_name} must not be empty")
    return normalized


__all__ = [
    "LocalOwnerUnavailableError",
    "OwnerMismatchError",
    "current_owner_id",
    "logged_out_owner_id",
    "register_logged_out_owner",
    "reset_logged_out_owner",
    "verify_current_owner",
]
