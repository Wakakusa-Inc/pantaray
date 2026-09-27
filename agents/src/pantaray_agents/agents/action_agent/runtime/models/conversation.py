"""Strict Supervisor / Goal Worker conversation state models."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

type MessageDirection = Literal["supervisor_to_worker", "worker_to_supervisor"]
type TurnStatus = Literal["running", "paused"]


def _require_non_blank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must not be blank")
    return value


def _require_iso8601(value: str) -> str:
    try:
        datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError("value must be an ISO 8601 timestamp") from exc
    return value


class GoalMessageModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    message_id: str
    sequence: int = Field(ge=1)
    direction: MessageDirection
    content: str
    created_at: str

    _validate_id = field_validator("message_id")(_require_non_blank)
    _validate_content = field_validator("content")(_require_non_blank)
    _validate_created_at = field_validator("created_at")(_require_iso8601)


class GoalWorkerTurnCursorModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    turn_number: int = Field(ge=1)
    trigger_sequence: int | None = Field(default=None, ge=1)
    generation: int = Field(ge=0)
    status: TurnStatus
    started_at: str

    _validate_started_at = field_validator("started_at")(_require_iso8601)


class GoalCompletionProposalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    proposal_id: str
    turn_number: int = Field(ge=1)
    output: str
    submitted_at: str

    _validate_id = field_validator("proposal_id")(_require_non_blank)
    _validate_output = field_validator("output")(_require_non_blank)
    _validate_submitted_at = field_validator("submitted_at")(_require_iso8601)


class GoalConversationStateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

    goal_id: str
    next_sequence: int = Field(default=1, ge=1)
    next_turn_number: int = Field(default=1, ge=1)
    supervisor_read_through_sequence: int = Field(default=0, ge=0)
    worker_read_through_sequence: int = Field(default=0, ge=0)
    messages: tuple[GoalMessageModel, ...] = ()
    active_turn: GoalWorkerTurnCursorModel | None = None
    pending_completion: GoalCompletionProposalModel | None = None

    _validate_goal_id = field_validator("goal_id")(_require_non_blank)

    @field_validator("messages", mode="before")
    @classmethod
    def normalize_json_messages(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @model_validator(mode="after")
    def validate_invariants(self) -> Self:
        sequences = tuple(message.sequence for message in self.messages)
        if sequences != tuple(sorted(sequences)) or len(set(sequences)) != len(
            sequences
        ):
            raise ValueError("message sequences must be unique and ascending")
        message_ids = tuple(message.message_id for message in self.messages)
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("message ids must be unique")
        maximum_sequence = sequences[-1] if sequences else 0
        if self.next_sequence <= maximum_sequence:
            raise ValueError("next_sequence must exceed every message sequence")
        if self.supervisor_read_through_sequence > maximum_sequence:
            raise ValueError("supervisor cursor exceeds the message sequence")
        if self.worker_read_through_sequence > maximum_sequence:
            raise ValueError("worker cursor exceeds the message sequence")
        maximum_worker_message = max(
            (
                message.sequence
                for message in self.messages
                if message.direction == "worker_to_supervisor"
            ),
            default=0,
        )
        if self.supervisor_read_through_sequence > maximum_worker_message:
            raise ValueError("supervisor cursor exceeds Worker messages")
        maximum_supervisor_message = max(
            (
                message.sequence
                for message in self.messages
                if message.direction == "supervisor_to_worker"
            ),
            default=0,
        )
        if self.worker_read_through_sequence > maximum_supervisor_message:
            raise ValueError("worker cursor exceeds Supervisor messages")
        if (
            self.active_turn is not None
            and self.active_turn.turn_number != self.next_turn_number - 1
        ):
            raise ValueError("active turn must be the latest Worker turn")
        if (
            self.active_turn is not None
            and self.active_turn.trigger_sequence is not None
        ):
            trigger = next(
                (
                    message
                    for message in self.messages
                    if message.sequence == self.active_turn.trigger_sequence
                ),
                None,
            )
            if trigger is None or trigger.direction != "supervisor_to_worker":
                raise ValueError(
                    "active turn trigger must reference a Supervisor message"
                )
        if self.active_turn is not None and self.pending_completion is not None:
            raise ValueError(
                "active turn and pending completion are mutually exclusive"
            )
        if (
            self.pending_completion is not None
            and self.pending_completion.turn_number != self.next_turn_number - 1
        ):
            raise ValueError("pending completion must belong to the latest Worker turn")
        return self


__all__ = [
    "GoalCompletionProposalModel",
    "GoalConversationStateModel",
    "GoalMessageModel",
    "GoalWorkerTurnCursorModel",
    "MessageDirection",
    "TurnStatus",
]
