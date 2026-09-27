"""Profile brief generation with bounded retries and explicit failure."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class BriefRetryPolicy:
    """profile brief 生成のリトライ/バリデーション設定。

    Attributes:
        max_attempts: 最大試行回数（生成失敗・不正出力時に再生成する）。
        min_chars: 不正出力とみなす最小文字数（strip後）。
    """

    max_attempts: int = 3
    min_chars: int = 20


class ProfileBriefGenerationError(RuntimeError):
    """Raised when every bounded profile-brief generation attempt fails."""


def build_insight_profile_brief_prompt(long_term_memory_text: str) -> str:
    """long-term insight tree本文から、Profile Brief を生成するための英語プロンプトを返す。

    Args:
        long_term_memory_text: Storageに保存される long-term insight tree の本文。

    Returns:
        英語の指示プロンプト（Markdown）。
    """
    src = (long_term_memory_text or "").strip()
    return (
        "Task: Generate a compact 'profile brief' for downstream agents.\n\n"
        "Constraints:\n"
        "- Keep it concise (target: <= ~400 tokens).\n"
        "- Return ONLY the brief text (no JSON, no tool calls, no XML tags).\n"
        "- You may follow the suggested format, but it is OK if you deviate.\n\n"
        "Suggested format (guideline, not strict):\n"
        "## Profile Brief\n"
        "- Key ongoing projects (1-3 bullets) (Confidence: X.X - reason)\n"
        "- Key goals (1-3 bullets) (Confidence: X.X - reason)\n"
        "- Key pain points / risks (1-3 bullets) (Confidence: X.X - reason)\n"
        "- Key preferences / working style (1-3 bullets) (Confidence: X.X - reason)\n\n"
        "Source memory tree (long-term insight):\n"
        "```text\n"
        f"{src}\n"
        "```\n"
    )


def build_facts_profile_brief_prompt(structured_facts_memory_text: str) -> str:
    """structured facts tree本文から、Profile Brief を生成するための英語プロンプトを返す。

    Args:
        structured_facts_memory_text: Storageに保存される facts tree の本文。

    Returns:
        英語の指示プロンプト（Markdown）。
    """
    src = (structured_facts_memory_text or "").strip()
    return (
        "Task: Generate a compact 'profile brief' for downstream agents.\n\n"
        "Purpose:\n"
        "- Summarize concrete facts that future agents may safely use as context.\n"
        "- Facts may cover any part of the user's work or life, not only software projects.\n"
        "- Keep preferences, habits, and judgment patterns out of this brief unless the source states an explicit rule, commitment, deadline, relationship, location, or current state.\n"
        "- Do not turn proposals, drafts, visible chat text, AI responses, or tentative designs into accepted facts.\n"
        "- Preserve uncertainty when the source marks an item as open or unconfirmed.\n\n"
        "Constraints:\n"
        "- Keep it concise (target: <= ~400 tokens).\n"
        "- Return ONLY the brief text (no JSON, no tool calls, no XML tags).\n"
        "- You may follow the suggested format, but it is OK if you deviate.\n\n"
        "Suggested format (guideline, not strict):\n"
        "## Profile Brief\n"
        "- What we know (3-8 bullets) (Confidence: X.X - reason)\n"
        "- Open questions / uncertainties (0-3 bullets) (Confidence: X.X - reason)\n"
        "- Most relevant items for decision making (1-3 bullets) (Confidence: X.X - reason)\n\n"
        "Source memory tree (structured facts):\n"
        "```text\n"
        f"{src}\n"
        "```\n"
    )


def _is_invalid_brief(text: str, *, min_chars: int) -> bool:
    """briefの不正判定（フォーマット逸脱は不正扱いしない）。"""
    normalized = (text or "").strip()
    return len(normalized) < int(min_chars)


def _augment_prompt_for_retry(base_prompt: str, *, reason: str) -> str:
    """再生成時に、直前失敗の理由を弱くフィードバックする。"""
    reason_text = (reason or "previous output was invalid").strip()
    return (
        f"{base_prompt}\n\n"
        "# System Note (retry)\n"
        f"The previous attempt failed or was invalid because: {reason_text}\n"
        "Please retry and return ONLY the brief text.\n"
    )


async def generate_profile_brief_with_retry(
    *,
    prompt: str,
    call_llm: Callable[[str], Awaitable[str]],
    policy: BriefRetryPolicy | None = None,
) -> str:
    """Generate a validated profile brief or fail after bounded retries.

    Args:
        prompt: LLMへ渡すプロンプト（英語推奨）。
        call_llm: prompt -> 生成テキスト を返す非同期関数。
        policy: リトライ/不正判定設定（省略時はデフォルト）。

    Returns:
        生成された profile brief（strip済み）。
    """
    pol = policy or BriefRetryPolicy()
    last_error: str | None = None

    for attempt in range(max(1, int(pol.max_attempts))):
        attempt_prompt = (
            _augment_prompt_for_retry(prompt, reason=last_error)
            if attempt > 0 and last_error
            else prompt
        )
        try:
            text = await call_llm(attempt_prompt)
        except Exception as exc:  # noqa: BLE001 - retry is the explicit boundary
            last_error = type(exc).__name__
            continue

        normalized = (text or "").strip()
        if not _is_invalid_brief(normalized, min_chars=pol.min_chars):
            return normalized

        last_error = "output was empty or too short"

    raise ProfileBriefGenerationError(
        f"profile brief generation failed after {pol.max_attempts} attempts: "
        f"{last_error or 'invalid output'}"
    )
