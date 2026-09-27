"""A persisted assistant utterance in the Action's chronological history."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt


class ActionAssistantMessageStep(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    step_id: str
    step_number: PositiveInt
    local_step_number: PositiveInt
    short_step_id: str
    content: str = Field(min_length=1)
    created_at: str
    assistant_phase: Literal["commentary"] | None = None


@dataclass(frozen=True, slots=True)
class ActionLlmTurnCommit:
    """Bind an adopted LLM step and its utterances to the exact USER owner."""

    user_step_id: str
    messages: tuple[ActionAssistantMessageStep, ...]
