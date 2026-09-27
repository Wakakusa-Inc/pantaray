"""Concrete OpenAI profiles for `pantaray_llm` provider tests.

`pantaray_llm` owns model-independent purposes; binding a purpose to a model is
the caller's decision (Cloud proxy, local direct routing). These tests only need
*some* concrete profile to drive the provider, so they bind here instead of
importing a caller's binding.
"""

from __future__ import annotations

from pantaray_llm.profiles import OPENAI_GPT_6_LUNA_MODEL
from pantaray_llm.profiles.purposes import DEFAULT_MAX_OUTPUT_TOKENS, LLM_PURPOSES
from pantaray_llm.providers.openai_responses.settings import OpenAiLlmProfile


def get_llm_profile(profile_id: str) -> OpenAiLlmProfile:
    purpose = LLM_PURPOSES[profile_id]
    return OpenAiLlmProfile(
        provider="openai",
        profile_id=purpose.id,
        model=OPENAI_GPT_6_LUNA_MODEL,
        max_output_tokens=DEFAULT_MAX_OUTPUT_TOKENS,
        reasoning_effort=purpose.reasoning_effort,
        image_detail=purpose.image_detail,
    )
