"""Strict public list models for Action and Suggestion history."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field
from pydantic_core import PydanticCustomError

from pantaray_agents.schema.action_conversation import (
    ActionConversationIdentity,
    NonBlankText,
)
from pantaray_agents.utils.timestamps import normalize_iso8601_utc_z_milliseconds

type ConversationHistoryStatus = Literal["running", "approval_pending", "idle"]


def _require_canonical_history_timestamp(value: str) -> str:
    try:
        canonical = normalize_iso8601_utc_z_milliseconds(value)
    except ValueError as exc:
        raise PydanticCustomError(
            "conversation_history_timestamp_invalid",
            "timestamp must use canonical UTC milliseconds",
        ) from exc
    if value != canonical:
        raise PydanticCustomError(
            "conversation_history_timestamp_invalid",
            "timestamp must use canonical UTC milliseconds",
        )
    return value


type ConversationHistoryTimestamp = Annotated[
    str, AfterValidator(_require_canonical_history_timestamp)
]


class _ConversationHistoryModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class ConversationHistoryItem(_ConversationHistoryModel):
    kind: Literal["conversation"]
    action_id: ActionConversationIdentity
    title: NonBlankText
    updated_at: ConversationHistoryTimestamp
    status: ConversationHistoryStatus
    latest_completion_event_id: ActionConversationIdentity | None


class SuggestionHistoryItem(_ConversationHistoryModel):
    kind: Literal["suggestion"]
    suggestion_id: ActionConversationIdentity
    title: NonBlankText
    updated_at: ConversationHistoryTimestamp
    status: Literal["approval_pending", "idle"]


type ConversationHistoryListItem = Annotated[
    ConversationHistoryItem | SuggestionHistoryItem,
    Field(discriminator="kind"),
]


class ConversationHistoryPage(_ConversationHistoryModel):
    items: tuple[ConversationHistoryListItem, ...]
    next_cursor: NonBlankText | None


__all__ = [
    "ConversationHistoryItem",
    "ConversationHistoryListItem",
    "ConversationHistoryPage",
    "ConversationHistoryStatus",
    "ConversationHistoryTimestamp",
    "SuggestionHistoryItem",
]
