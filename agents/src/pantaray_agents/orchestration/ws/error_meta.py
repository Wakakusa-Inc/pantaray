"""公開 WS error meta の型と helper。"""

from __future__ import annotations

from typing import Literal, NotRequired, TypedDict

from pantaray_agents.schema.agent.base import JSONValue

ErrorMetaKind = Literal["action", "suggestion", "session", "protocol"]


class SuggestionErrorMeta(TypedDict):
    """Suggestion detail に属する公開 error meta。"""

    kind: Literal["suggestion"]
    suggestion_id: str
    stage: str
    error_code: str
    process_id: NotRequired[str]
    failure_kind: NotRequired[str]


class SessionErrorMeta(TypedDict):
    """WS セッション単位の公開 error meta。"""

    kind: Literal["session"]
    stage: str
    error_code: str
    process_id: NotRequired[str]


class ProtocolErrorMeta(TypedDict):
    """protocol/validation 系の公開 error meta。"""

    kind: Literal["protocol"]
    stage: str
    error_code: str


def build_suggestion_error_meta(
    *,
    suggestion_id: str,
    stage: str,
    error_code: str,
    process_id: str | None = None,
    failure_kind: str | None = None,
) -> SuggestionErrorMeta:
    meta: SuggestionErrorMeta = {
        "kind": "suggestion",
        "suggestion_id": str(suggestion_id),
        "stage": str(stage),
        "error_code": str(error_code),
    }
    if process_id:
        meta["process_id"] = str(process_id)
    if failure_kind:
        meta["failure_kind"] = str(failure_kind)
    return meta


def build_session_error_meta(
    *,
    stage: str,
    error_code: str,
    process_id: str | None = None,
) -> SessionErrorMeta:
    meta: SessionErrorMeta = {
        "kind": "session",
        "stage": str(stage),
        "error_code": str(error_code),
    }
    if process_id:
        meta["process_id"] = str(process_id)
    return meta


def build_protocol_error_meta(
    *,
    stage: str,
    error_code: str,
) -> ProtocolErrorMeta:
    return {
        "kind": "protocol",
        "stage": str(stage),
        "error_code": str(error_code),
    }


def normalize_error_meta_kind(value: JSONValue | None) -> ErrorMetaKind:
    if value == "action":
        return "action"
    if value == "suggestion":
        return "suggestion"
    if value == "session":
        return "session"
    if value == "protocol":
        return "protocol"
    raise ValueError(f"Unsupported public error meta kind: {value!r}")


__all__ = [
    "ErrorMetaKind",
    "ProtocolErrorMeta",
    "SessionErrorMeta",
    "SuggestionErrorMeta",
    "build_protocol_error_meta",
    "build_session_error_meta",
    "build_suggestion_error_meta",
    "normalize_error_meta_kind",
]
