"""Strict opaque keyset cursor for the conversation history list."""

from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, TypeAdapter
from pydantic_core import PydanticCustomError

from pantaray_agents.schema.action_conversation import ActionConversationIdentity
from pantaray_agents.schema.conversation_history import ConversationHistoryTimestamp

from .cursor_codec import decode_opaque_cursor, encode_opaque_cursor


def _require_normalized_search_text(value: str) -> str:
    if value != value.strip().casefold():
        raise PydanticCustomError(
            "conversation_history_search_not_normalized",
            "search text must be stripped and case-folded",
        )
    return value


type _NormalizedSearchText = Annotated[
    str, AfterValidator(_require_normalized_search_text)
]


class ConversationHistoryCursor(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )

    user_id: ActionConversationIdentity
    search_text: _NormalizedSearchText
    updated_at: ConversationHistoryTimestamp
    kind: Literal["conversation", "suggestion"]
    stable_id: ActionConversationIdentity


_CURSOR_ADAPTER = TypeAdapter(ConversationHistoryCursor)


def encode_conversation_history_cursor(payload: ConversationHistoryCursor) -> str:
    return encode_opaque_cursor(payload, adapter=_CURSOR_ADAPTER)


def decode_conversation_history_cursor(value: str) -> ConversationHistoryCursor:
    return decode_opaque_cursor(value, adapter=_CURSOR_ADAPTER)


__all__ = [
    "ConversationHistoryCursor",
    "decode_conversation_history_cursor",
    "encode_conversation_history_cursor",
]
