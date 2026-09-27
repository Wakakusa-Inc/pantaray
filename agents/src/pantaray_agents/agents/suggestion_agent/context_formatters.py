"""SuggestionAgent のコンテキスト整形ヘルパー。"""

import logging
from collections.abc import Mapping

from pantaray_agents.schema.agent.suggestion import (
    SuggestionHistoryEntry,
)
from pantaray_agents.schema.repositories.repository import JSONValue
from pantaray_agents.utils.local_time import describe_utc_timestamp, local_period

from .context_density import is_activity_summary_row_present
from .context_types import ActivityDescriptionRow, ActivitySummaryRow

NO_ACTIVITY_DESCRIPTIONS_TEXT = "(no activity descriptions available)"
NO_ACTIVITY_SUMMARY_1H_TEXT = "(no 1h summary available)"
NO_RECENT_ANSWERS_TEXT = "(no recent answers)"
RECENT_SUGGESTION_REPLY_MAX_CHARS = 2_000

logger = logging.getLogger(__name__)


def format_activity_descriptions(rows: list[ActivityDescriptionRow] | None) -> str:
    """直近のActivity Descriptionログをプロンプト用に整形（新しい順）。"""
    if not rows:
        return NO_ACTIVITY_DESCRIPTIONS_TEXT

    lines: list[str] = []
    for row in rows:
        desc = str(row.get("description") or "").strip()
        period = local_period(row["period_start"], row["period_end"])
        lines.append(f"- [{period}] {desc}")
    return "\n".join(lines)


def format_activity_summary(rows: list[ActivitySummaryRow] | None) -> str:
    """直近1時間サマリを1件だけ整形する。

    present 判定は Context Availability と同じ。材料のない「活動なし」の定型文は、
    スロットと同じく「無い」ことだけを伝える。
    """
    if not rows or not is_activity_summary_row_present(rows[0]):
        return NO_ACTIVITY_SUMMARY_1H_TEXT

    row = rows[0]
    summary = str(row.get("summary") or "").strip()
    period = local_period(row["period_start"], row["period_end"])
    return f"[{period}] {summary}"


def format_recent_suggestions(rows: list[SuggestionHistoryEntry] | None) -> str:
    """直近の提案と記録された反応・返信を整形する。"""
    if not rows:
        return NO_RECENT_ANSWERS_TEXT

    lines: list[str] = []
    for row in rows:
        created_at = describe_utc_timestamp(row.created_at)
        lines.append(f"- [{created_at}] answer: {row.answer}")
        lines.append(f"  User reaction: {row.user_reaction or 'not recorded'}")
        if row.user_reply is not None:
            reply = row.user_reply[:RECENT_SUGGESTION_REPLY_MAX_CHARS]
            if len(row.user_reply) > RECENT_SUGGESTION_REPLY_MAX_CHARS:
                reply += "\n[reply truncated]"
            lines.append(f"  User reply: {reply}")
    return "\n".join(lines)


def normalize_recent_suggestion_entry(
    row: Mapping[str, JSONValue] | None,
) -> SuggestionHistoryEntry | None:
    """Repository 取得行を SuggestionHistoryEntry へ正規化する。"""
    if row is None or not isinstance(row, Mapping):
        logger.debug(
            "Skip recent suggestion row because it is not a mapping: %s",
            type(row).__name__,
        )
        return None

    answer = str(row.get("answer") or "")
    created_at = str(row.get("created_at") or "")
    raw_thinking = row.get("thinking")
    thinking = None if raw_thinking is None else str(raw_thinking)
    return SuggestionHistoryEntry.model_validate(
        {
            "answer": answer,
            "created_at": created_at,
            "thinking": thinking,
            "user_reaction": row.get("user_reaction"),
            "user_reply": row.get("user_reply"),
        }
    )
