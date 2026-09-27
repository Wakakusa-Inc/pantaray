"""Task-layer compatibility adapter for the canonical Action USER codec."""

from __future__ import annotations

from pydantic import ValidationError

from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.schema.agent.action_message import ActionUserMessageInput
from pantaray_agents.schema.agent.action_message_codec import (
    parse_action_user_message as _parse_action_user_message,
)
from pantaray_agents.schema.agent.action_message_codec import (
    render_action_user_request_text as _render_action_user_request_text,
)
from pantaray_agents.schema.agent.action_message_codec import (
    serialize_action_user_message as _serialize_action_user_message,
)


def serialize_action_user_message(message: ActionUserMessageInput) -> str:
    """Serialize one validated input to canonical durable JSON."""

    return _serialize_action_user_message(message)


def parse_action_user_message(message_json: str) -> ActionUserMessageInput:
    """Parse and validate one durable USER message without fallback coercion."""

    try:
        return _parse_action_user_message(message_json)
    except ValidationError as exc:
        raise MigrationError("Action USER message does not match V1 schema") from exc


def render_action_user_request_text(message: ActionUserMessageInput) -> str:
    """Render the complete USER text used by history and prompt construction."""

    return _render_action_user_request_text(message)


__all__ = [
    "parse_action_user_message",
    "render_action_user_request_text",
    "serialize_action_user_message",
]
