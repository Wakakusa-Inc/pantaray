from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

ANTHROPIC_MIN_THINKING_BUDGET_TOKENS = 1024


@dataclass(frozen=True, slots=True)
class AnthropicAdaptiveThinking:
    effort: Literal["low", "medium", "high", "xhigh", "max"]


@dataclass(frozen=True, slots=True)
class AnthropicBudgetThinking:
    budget_tokens: int


@dataclass(frozen=True, slots=True)
class AnthropicLlmProfile:
    provider: Literal["anthropic"]
    profile_id: str
    model: str
    max_output_tokens: int
    # None leaves the model's default behavior intact. New models use adaptive
    # thinking; manual budget thinking is only supported by earlier models.
    thinking: AnthropicAdaptiveThinking | AnthropicBudgetThinking | None = None
    enable_image_inputs: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.thinking, AnthropicBudgetThinking) and not (
            ANTHROPIC_MIN_THINKING_BUDGET_TOKENS
            <= self.thinking.budget_tokens
            < self.max_output_tokens
        ):
            raise ValueError(
                f"thinking.budget_tokens must be in "
                f"[{ANTHROPIC_MIN_THINKING_BUDGET_TOKENS}, {self.max_output_tokens}): "
                f"{self.profile_id}."
            )
