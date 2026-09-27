from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pantaray_llm.profiles import ReasoningEffort
from pantaray_llm.providers.openai_responses.transport import OpenAiResponsesProvider


@dataclass(frozen=True, slots=True)
class OpenAiLlmProfile:
    provider: OpenAiResponsesProvider
    profile_id: str
    model: str
    max_output_tokens: int | None
    reasoning_effort: ReasoningEffort | None
    image_detail: Literal["low", "high", "original", "auto"] | None = None


__all__ = ["OpenAiLlmProfile"]
