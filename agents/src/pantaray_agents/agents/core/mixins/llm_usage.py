from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Protocol

from pydantic import BaseModel

from pantaray_agents.schema.agent.base import AgentError

type LlmUsageTotals = dict[str, int]


@dataclass(frozen=True, slots=True)
class LlmUsage:
    """One high-level LLM invocation's complete token usage."""

    prompt_tokens: int | None
    completion_tokens: int | None
    fields: Mapping[str, int] = field(default_factory=dict)


class TokenSink(Protocol):
    """Required accounting contract for every high-level LLM invocation."""

    @property
    def delta(self) -> LlmUsage: ...

    def guard(self) -> None: ...

    def record(
        self,
        usage: LlmUsage,
        *,
        stage: str | None,
        may_raise: bool,
    ) -> None: ...


class TokenBudgetExceeded(RuntimeError):
    """Raised after usage has been recorded and the action budget is exhausted."""

    def __init__(self, error: AgentError, sink: TokenSink) -> None:
        super().__init__(error.error_message or error.error_code)
        self.error = error
        self.sink = sink


def add_llm_usage(left: LlmUsage, right: LlmUsage) -> LlmUsage:
    """Return the field-wise and canonical-token sum of two usage records."""

    fields = dict(left.fields)
    for key, value in right.fields.items():
        fields[key] = fields.get(key, 0) + value

    def _add_optional(a: int | None, b: int | None) -> int | None:
        if a is None:
            return b
        if b is None:
            return a
        return a + b

    return LlmUsage(
        prompt_tokens=_add_optional(left.prompt_tokens, right.prompt_tokens),
        completion_tokens=_add_optional(
            left.completion_tokens,
            right.completion_tokens,
        ),
        fields=fields,
    )


class CountingSink:
    """Run-scoped token counter for callers without an action budget."""

    def __init__(self) -> None:
        self._delta = LlmUsage(None, None)

    @property
    def delta(self) -> LlmUsage:
        return self._delta

    def guard(self) -> None:
        return None

    def record(
        self,
        usage: LlmUsage,
        *,
        stage: str | None,
        may_raise: bool,
    ) -> None:
        del stage, may_raise
        self._delta = add_llm_usage(self._delta, usage)


def _usage_values(usage_metadata: object | None) -> dict[str, object]:
    if usage_metadata is None:
        return {}
    if isinstance(usage_metadata, dict):
        nested = usage_metadata.get("usage_metadata")
        return _usage_values(nested) if nested is not None else usage_metadata
    nested = getattr(usage_metadata, "usage_metadata", None)
    if isinstance(nested, dict | BaseModel):
        return _usage_values(nested)
    if isinstance(usage_metadata, BaseModel):
        return usage_metadata.model_dump(exclude_none=True)
    try:
        return {
            key: value
            for key, value in vars(usage_metadata).items()
            if not key.startswith("_")
        }
    except TypeError:
        return {}


def accumulate_llm_usage(
    accumulated: LlmUsageTotals,
    usage_metadata: object | None,
) -> LlmUsageTotals:
    """Return per-field token totals without mutating either input."""

    result = dict(accumulated)
    for key, value in _usage_values(usage_metadata).items():
        if (
            isinstance(key, str)
            and isinstance(value, int)
            and not isinstance(value, bool)
        ):
            result[key] = result.get(key, 0) + value
    return result


def _coerce_token_count(value: object | None) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if not isinstance(value, str | float):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _unwrap_usage_metadata(usage_metadata: object) -> object:
    if isinstance(usage_metadata, dict):
        nested = usage_metadata.get("usage_metadata")
    else:
        nested = getattr(usage_metadata, "usage_metadata", None)
    return nested if nested is not None else usage_metadata


def _get_usage_value(usage_metadata: object, key: str) -> object | None:
    if isinstance(usage_metadata, dict):
        return usage_metadata.get(key)
    return getattr(usage_metadata, key, None)


def _first_token_count(usage_metadata: object, keys: tuple[str, ...]) -> int | None:
    for key in keys:
        value = _coerce_token_count(_get_usage_value(usage_metadata, key))
        if value is not None:
            return value
    return None


def _extract_token_counts(
    usage_metadata: object | None,
) -> tuple[int | None, int | None]:
    """Extract prompt and completion token counts from provider metadata."""

    if usage_metadata is None:
        return None, None

    usage_metadata = _unwrap_usage_metadata(usage_metadata)
    prompt_tokens = _first_token_count(
        usage_metadata,
        (
            "prompt_token_count",
            "input_token_count",
            "cached_content_token_count",
            "prompt_tokens",
            "input_tokens",
        ),
    )
    completion_tokens = _first_token_count(
        usage_metadata,
        (
            "candidates_token_count",
            "output_token_count",
            "completion_token_count",
            "completion_tokens",
            "output_tokens",
        ),
    )
    total_tokens = _first_token_count(
        usage_metadata,
        ("total_token_count", "total_tokens"),
    )

    if (
        prompt_tokens is None
        and total_tokens is not None
        and completion_tokens is not None
    ):
        inferred = total_tokens - completion_tokens
        prompt_tokens = inferred if inferred >= 0 else None
    if (
        completion_tokens is None
        and total_tokens is not None
        and prompt_tokens is not None
    ):
        inferred = total_tokens - prompt_tokens
        completion_tokens = inferred if inferred >= 0 else None

    return prompt_tokens, completion_tokens


def llm_usage_from_metadata(usage_metadata: object | None) -> LlmUsage:
    """Normalize one transport attempt's provider metadata into usage."""

    prompt_tokens, completion_tokens = _extract_token_counts(usage_metadata)
    return LlmUsage(
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        fields=accumulate_llm_usage({}, usage_metadata),
    )


def add_usage_metadata(
    usage: LlmUsage,
    usage_metadata: object | None,
) -> LlmUsage:
    """Return a ledger with one transport attempt's metadata added."""

    return add_llm_usage(usage, llm_usage_from_metadata(usage_metadata))


__all__ = [
    "CountingSink",
    "LlmUsage",
    "LlmUsageTotals",
    "TokenBudgetExceeded",
    "TokenSink",
    "_extract_token_counts",
    "add_llm_usage",
    "add_usage_metadata",
    "accumulate_llm_usage",
    "llm_usage_from_metadata",
]
