from __future__ import annotations

_GLOBAL_SCOPE_REF_TOKEN = "global"
_APPROVAL_PREFERENCE_ID_PREFIX = "approval-preference"
_CAPABILITY_GRANT_ID_PREFIX = "capability-grant"
_APPLIES_TO_SEPARATOR = "+"


def _scope_ref_token(scope_ref: str | None) -> str:
    return scope_ref if scope_ref is not None else _GLOBAL_SCOPE_REF_TOKEN


def _applies_to_token(applies_to: tuple[str, ...]) -> str:
    return _APPLIES_TO_SEPARATOR.join(sorted(applies_to))


def build_approval_preference_id(
    *,
    user_id: str,
    scope_type: str,
    scope_ref: str | None,
    applies_to: tuple[str, ...],
) -> str:
    return (
        f"{_APPROVAL_PREFERENCE_ID_PREFIX}:{user_id}:{scope_type}:"
        f"{_scope_ref_token(scope_ref)}:{_applies_to_token(applies_to)}"
    )


def build_capability_grant_id(
    *,
    user_id: str,
    scope_type: str,
    scope_ref: str | None,
    capability: str,
    applies_to: tuple[str, ...],
) -> str:
    return (
        f"{_CAPABILITY_GRANT_ID_PREFIX}:{user_id}:{scope_type}:"
        f"{_scope_ref_token(scope_ref)}:{capability}:{_applies_to_token(applies_to)}"
    )
