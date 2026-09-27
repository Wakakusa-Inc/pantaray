"""Convert persisted agent failures into the public WebSocket error contract."""

from __future__ import annotations

from collections.abc import Mapping

from pydantic import ValidationError

from pantaray_agents.schema.agent.base import AgentError, ErrorSeverity, ErrorType
from pantaray_agents.schema.websocket.server_messages import ErrorMessage
from pantaray_agents.utils.public_error import (
    PUBLIC_INTERNAL_ERROR_MESSAGE,
    public_ws_error,
)

_PUBLIC_MESSAGE_BY_TYPE: dict[str, str] = {
    "validation_error": "The operation could not continue because its input was invalid.",
    "authentication_error": "Authentication is required to continue.",
    "authorization_error": "This operation is not permitted.",
    "conflict_error": "The operation conflicted with the current state.",
    "capacity_error": "The operation reached its execution limit.",
    "rate_limit_error": "The service is temporarily rate limited.",
    "llm_api_error": "The AI service could not complete the operation.",
    "llm_output_error": "The AI response could not be processed.",
    "tool_execution_error": "A required tool could not complete the operation.",
    "repository_error": "The operation could not be saved.",
    "dependency_error": "A required service was unavailable.",
    "timeout_error": "The operation timed out.",
    "canceled_error": "The operation was canceled.",
    "internal_error": "The operation failed due to an internal error.",
}
_DEFAULT_PUBLIC_MESSAGE = PUBLIC_INTERNAL_ERROR_MESSAGE
_CANONICAL_TYPE_BY_INTERNAL_TYPE: dict[str, ErrorType] = {
    "budget_exceeded": ErrorType.CAPACITY_ERROR,
    "persistence_error": ErrorType.REPOSITORY_ERROR,
    "runtime_timeout": ErrorType.TIMEOUT_ERROR,
    "runtime_error": ErrorType.INTERNAL_ERROR,
    "resume_error": ErrorType.INTERNAL_ERROR,
    "start_lane_error": ErrorType.INTERNAL_ERROR,
}


def _request_id_from_payload(payload: Mapping[str, object]) -> str | None:
    details = payload.get("error_details")
    if isinstance(details, Mapping):
        request_id = details.get("request_id")
        if isinstance(request_id, str):
            return request_id
    request_id = payload.get("request_id")
    return request_id if isinstance(request_id, str) else None


def _public_error_type(value: str) -> ErrorType:
    mapped = _CANONICAL_TYPE_BY_INTERNAL_TYPE.get(value)
    if mapped is not None:
        return mapped
    try:
        return ErrorType(value)
    except ValueError:
        return ErrorType.INTERNAL_ERROR


def _public_error_severity(value: str) -> ErrorSeverity:
    try:
        return ErrorSeverity(value)
    except ValueError:
        return ErrorSeverity.ERROR


def error_from_payload(
    payload: Mapping[str, object] | None,
    default_code: str,
) -> ErrorMessage:
    """Build a safe public error without discarding a valid stable error code.

    Agent-owned details and raw messages remain private.  Only validated
    classification fields cross the public boundary.  ``default_code`` is used
    exclusively when the persisted payload itself is malformed.
    """

    if not isinstance(payload, Mapping):
        return public_ws_error(
            error_code=default_code,
            error_message=_DEFAULT_PUBLIC_MESSAGE,
        )
    request_id = _request_id_from_payload(payload)
    try:
        parsed = AgentError.model_validate(dict(payload))
    except ValidationError:
        return public_ws_error(
            error_code=default_code,
            request_id=request_id,
            error_message=_DEFAULT_PUBLIC_MESSAGE,
        )
    normalized_code = parsed.error_code.strip()
    if not normalized_code:
        normalized_code = default_code
    internal_type = parsed.error_type.strip().lower()
    public_type = _public_error_type(internal_type)
    return public_ws_error(
        error_code=normalized_code,
        request_id=request_id,
        error_type=public_type,
        severity=_public_error_severity(parsed.severity.strip().lower()),
        error_message=_PUBLIC_MESSAGE_BY_TYPE.get(
            public_type.value,
            _DEFAULT_PUBLIC_MESSAGE,
        ),
    )
