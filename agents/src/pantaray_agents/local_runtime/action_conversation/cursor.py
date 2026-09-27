"""Strict keyset cursor payloads for durable Action conversation history."""

from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from pantaray_agents.schema.action_conversation import ActionConversationIdentity

from .cursor_codec import decode_opaque_cursor, encode_opaque_cursor

SQLITE_INTEGER_MAX = (1 << 63) - 1
type SQLitePositiveInteger = Annotated[
    int,
    Field(gt=0, le=SQLITE_INTEGER_MAX),
]


class _ActionConversationCursorModel(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )


class ActionConversationRunBoundary(_ActionConversationCursorModel):
    run_id: ActionConversationIdentity
    step_number: SQLitePositiveInteger
    step_id: ActionConversationIdentity


class ActionConversationUnadoptedFrontier(_ActionConversationCursorModel):
    accepted_sequence: SQLitePositiveInteger
    step_id: ActionConversationIdentity


class ActionConversationTimelineCursor(_ActionConversationCursorModel):
    user_id: ActionConversationIdentity
    action_id: ActionConversationIdentity
    scope: Literal["current_timeline", "older_timeline"]
    step_number: SQLitePositiveInteger
    step_id: ActionConversationIdentity
    timeline_ceiling: ActionConversationRunBoundary | None

    @model_validator(mode="after")
    def require_current_timeline_ceiling(self) -> Self:
        if (self.scope == "current_timeline") != (self.timeline_ceiling is not None):
            raise ValueError("timeline ceiling must match cursor scope")
        return self


class ActionConversationUnadoptedCursor(_ActionConversationCursorModel):
    user_id: ActionConversationIdentity
    action_id: ActionConversationIdentity
    scope: Literal["unadopted"]
    accepted_sequence: SQLitePositiveInteger
    step_id: ActionConversationIdentity
    timeline_boundary: ActionConversationRunBoundary | None
    timeline_ceiling: ActionConversationRunBoundary | None
    unadopted_ceiling: ActionConversationUnadoptedFrontier

    @model_validator(mode="after")
    def require_matching_timeline_authorities(self) -> Self:
        if (self.timeline_boundary is None) != (self.timeline_ceiling is None):
            raise ValueError("timeline boundary and ceiling must both be present")
        return self


type ActionConversationCursor = Annotated[
    ActionConversationTimelineCursor | ActionConversationUnadoptedCursor,
    Field(discriminator="scope"),
]

_CURSOR_ADAPTER: TypeAdapter[ActionConversationCursor] = TypeAdapter(
    ActionConversationCursor
)


def encode_action_conversation_cursor(payload: ActionConversationCursor) -> str:
    return encode_opaque_cursor(payload, adapter=_CURSOR_ADAPTER)


def decode_action_conversation_cursor(value: str) -> ActionConversationCursor:
    return decode_opaque_cursor(value, adapter=_CURSOR_ADAPTER)
