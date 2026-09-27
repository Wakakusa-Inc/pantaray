from __future__ import annotations

import pytest

from pantaray_agents.utils.profile_brief import (
    BriefRetryPolicy,
    ProfileBriefGenerationError,
    build_facts_profile_brief_prompt,
    generate_profile_brief_with_retry,
)


def test_facts_profile_brief_prompt_preserves_fact_boundary() -> None:
    prompt = build_facts_profile_brief_prompt("# Structured Facts\n")

    assert "concrete facts that future agents may safely use as context" in prompt
    assert "not only software projects" in prompt
    assert "Keep preferences, habits, and judgment patterns out" in prompt
    assert "Do not turn proposals, drafts, visible chat text" in prompt
    assert "Preserve uncertainty" in prompt


@pytest.mark.asyncio
async def test_profile_brief_retries_then_returns_valid_output() -> None:
    responses = iter(("", "A sufficiently detailed profile brief."))

    async def call_llm(_prompt: str) -> str:
        return next(responses)

    result = await generate_profile_brief_with_retry(
        prompt="prompt",
        call_llm=call_llm,
        policy=BriefRetryPolicy(max_attempts=2, min_chars=20),
    )

    assert result == "A sufficiently detailed profile brief."


@pytest.mark.asyncio
async def test_profile_brief_fails_closed_after_bounded_attempts() -> None:
    attempts = 0

    async def call_llm(_prompt: str) -> str:
        nonlocal attempts
        attempts += 1
        raise ConnectionError("provider detail must not be propagated")

    with pytest.raises(
        ProfileBriefGenerationError,
        match="failed after 2 attempts: ConnectionError",
    ) as exc_info:
        await generate_profile_brief_with_retry(
            prompt="prompt",
            call_llm=call_llm,
            policy=BriefRetryPolicy(max_attempts=2),
        )

    assert attempts == 2
    assert "provider detail" not in str(exc_info.value)
