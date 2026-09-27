"""ActionAgent のクライアント向けエラー赤化ユーティリティ。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping

from pydantic import ValidationError

from pantaray_agents.schema.agent.base import AgentError, JSONValue
from pantaray_agents.utils.public_error import PUBLIC_INTERNAL_ERROR_MESSAGE

_CLIENT_FALLBACK_ERROR_CODE = "ACTION_CLIENT_ERROR_PAYLOAD_INVALID"

type ActionErrorPayload = Mapping[str, JSONValue]


def redact_agent_error_for_client(error: AgentError) -> AgentError:
    """クライアント公開用に AgentError の詳細情報を除去する。"""
    return AgentError(
        error_type=error.error_type,
        error_code=error.error_code,
        error_message=PUBLIC_INTERNAL_ERROR_MESSAGE,
        error_details=None,
        severity=error.severity,
        metadata=None,
    )


def redact_agent_error_payload_for_client(
    error_payload: ActionErrorPayload,
) -> dict[str, JSONValue]:
    """クライアント公開用に error payload を赤化して返す。"""
    try:
        parsed = AgentError.model_validate(error_payload)
    except ValidationError:
        fallback = AgentError(
            error_type="internal_error",
            error_code=_CLIENT_FALLBACK_ERROR_CODE,
            error_message=PUBLIC_INTERNAL_ERROR_MESSAGE,
            error_details=None,
            severity="error",
            metadata=None,
        )
        return _agent_error_payload(fallback)
    return _agent_error_payload(redact_agent_error_for_client(parsed))


async def emit_redacted_error_payload(
    emit_error: Callable[[ActionErrorPayload], Awaitable[None]],
    payload: ActionErrorPayload,
) -> None:
    """error payload を赤化してクライアントへ送信する。"""
    await emit_error(redact_agent_error_payload_for_client(payload))


async def emit_redacted_agent_error(
    emit_error: Callable[[ActionErrorPayload], Awaitable[None]],
    error: AgentError,
) -> None:
    """AgentError を赤化してクライアントへ送信する。"""
    await emit_redacted_error_payload(
        emit_error,
        _agent_error_payload(error),
    )


def _agent_error_payload(error: AgentError) -> dict[str, JSONValue]:
    payload = error.model_dump()
    return {str(key): value for key, value in payload.items()}


__all__ = [
    "ActionErrorPayload",
    "emit_redacted_agent_error",
    "emit_redacted_error_payload",
    "redact_agent_error_for_client",
    "redact_agent_error_payload_for_client",
]
