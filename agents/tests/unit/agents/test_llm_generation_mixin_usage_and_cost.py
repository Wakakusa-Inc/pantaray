from __future__ import annotations

from types import SimpleNamespace

import pytest

from pantaray_agents.agents.core.mixins.llm_generation_mixin import LLMGenerationMixin
from pantaray_agents.agents.core.mixins.llm_usage import _extract_token_counts


@pytest.mark.parametrize(
    ("usage", "expected"),
    [
        ({"prompt_token_count": 11, "candidates_token_count": 22}, (11, 22)),
        (SimpleNamespace(prompt_token_count=3, output_token_count=7), (3, 7)),
        (
            {
                "usage_metadata": {
                    "prompt_token_count": 5,
                    "candidates_token_count": 9,
                }
            },
            (5, 9),
        ),
        ({"total_token_count": 12, "candidates_token_count": 7}, (5, 7)),
        ({"total_token_count": 12, "prompt_token_count": 5}, (5, 7)),
        (
            {
                "candidates_token_count": 13,
                "output_token_count": 17,
                "completion_token_count": 19,
            },
            (None, 13),
        ),
        (
            {
                "prompt_token_count": True,
                "input_token_count": 4,
                "candidates_token_count": False,
                "output_token_count": 6,
            },
            (4, 6),
        ),
        (None, (None, None)),
    ],
)
def test_extract_token_counts(
    usage: object | None,
    expected: tuple[int | None, int | None],
) -> None:
    assert _extract_token_counts(usage) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gemini-3-flash-preview", "gemini-3-flash-preview"),
        ("Gemini-3-Flash-Preview", "gemini-3-flash-preview"),
        ("publishers/google/models/gemini-3-flash-preview", "gemini-3-flash-preview"),
        (
            "publishers/google/models/gemini-3-flash-preview@001",
            "gemini-3-flash-preview",
        ),
    ],
)
def test_normalize_model_name(raw: str, expected: str) -> None:
    """pricing lookup で一致しやすい形にモデル名が正規化されることを確認。"""
    assert LLMGenerationMixin._normalize_model_name(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("gemini-3-flash-preview", True),
        ("gemini-3.1-flash-lite", True),
        ("publishers/google/models/gemini-3.1-flash-lite@001", True),
        ("gemini-2.5-flash-lite", False),
    ],
)
def test_is_gemini_3_flash_model(raw: str, expected: bool) -> None:
    """Gemini 3 / 3.1 Flash 系だけを既定最適化の対象にする。"""
    assert LLMGenerationMixin._is_gemini_3_flash_model(raw) is expected
