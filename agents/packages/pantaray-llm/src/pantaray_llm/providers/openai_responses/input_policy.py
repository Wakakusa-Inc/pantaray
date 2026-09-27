from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from openai import AsyncOpenAI
from openai.types.responses.input_token_count_params import InputTokenCountParams
from openai.types.responses.response_create_params import (
    ResponseCreateParamsNonStreaming,
)

from pantaray_llm.errors import PROXY_INVALID_INPUT, ProviderError

OPENAI_MAX_INPUT_TOKENS = 272_000
_INPUT_TOKEN_COUNT_FIELDS = (
    "input",
    "instructions",
    "model",
    "parallel_tool_calls",
    "reasoning",
    "text",
    "tool_choice",
    "tools",
    "truncation",
)


async def require_openai_input_within_limit(
    *,
    client: AsyncOpenAI,
    create_kwargs: ResponseCreateParamsNonStreaming,
) -> None:
    raw_create_kwargs = cast(Mapping[str, object], create_kwargs)
    count_kwargs = cast(
        InputTokenCountParams,
        {
            field: raw_create_kwargs[field]
            for field in _INPUT_TOKEN_COUNT_FIELDS
            if field in raw_create_kwargs
        },
    )
    result = await client.responses.input_tokens.count(**count_kwargs)
    if result.input_tokens > OPENAI_MAX_INPUT_TOKENS:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message="OpenAI input exceeds the supported token limit.",
            details={
                "input_tokens": result.input_tokens,
                "max_input_tokens": OPENAI_MAX_INPUT_TOKENS,
            },
        )


__all__ = ["OPENAI_MAX_INPUT_TOKENS", "require_openai_input_within_limit"]
