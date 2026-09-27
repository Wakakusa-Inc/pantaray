from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.llm_proxy.response_parsing import read_llm_provider


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("openai", "openai"),
        ("openai_codex", "openai_codex"),
        ("fireworks", "fireworks"),
        ("anthropic", "anthropic"),
        ("tavily", None),
        (None, None),
    ],
)
def test_read_llm_provider_accepts_every_llm_provider(
    value: str | None, expected: str | None
) -> None:
    payload = {} if value is None else {"upstream_provider": value}
    assert read_llm_provider(payload) == expected
