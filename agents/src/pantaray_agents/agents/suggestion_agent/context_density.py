"""SuggestionAgent の context density 計算ヘルパー。"""

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime

from pantaray_agents.utils.local_time import (
    describe_local_time,
    describe_utc_timestamp,
    local_zone_name,
)

from .context_types import (
    ActivityDescriptionRow,
    ActivitySummaryRow,
    ContextDensitySlotStatus,
    SummaryType,
)

CONTEXT_DENSITY_SLOT_ORDER: tuple[tuple[str, str], ...] = (
    ("activity_descriptions", "Activity Description (recent 3)"),
    ("activity_summary_1h", "Activity Summary (1h)"),
    ("activity_summary_24h", "Activity Summary (24h)"),
    ("activity_summary_1w", "Activity Summary (1w)"),
    ("activity_summary_1m", "Activity Summary (1m)"),
    ("long_term_insight", "Long-term Insight"),
    ("long_term_facts", "Long-term Facts"),
)
CONTEXT_DENSITY_LOW_MAX_PRESENT = 2
CONTEXT_DENSITY_MEDIUM_MAX_PRESENT = 4

SUMMARY_TYPE_24H: SummaryType = "24h"
SUMMARY_TYPE_1W: SummaryType = "1w"
SUMMARY_TYPE_1M: SummaryType = "1m"
SUMMARY_TYPES_24H_1W_1M: tuple[SummaryType, SummaryType, SummaryType] = (
    SUMMARY_TYPE_24H,
    SUMMARY_TYPE_1W,
    SUMMARY_TYPE_1M,
)

SECONDS_PER_MINUTE = 60
SECONDS_PER_HOUR = 60 * SECONDS_PER_MINUTE
SECONDS_PER_DAY = 24 * SECONDS_PER_HOUR
MINUTES_FORMAT_MAX_SECONDS = 2 * SECONDS_PER_HOUR
HOURS_FORMAT_MAX_SECONDS = 48 * SECONDS_PER_HOUR


def parse_iso_datetime(value: str | datetime | None) -> datetime | None:
    """ISO 8601 文字列（Z / +00:00 を含む）をUTCのdatetimeへ変換する（失敗時はNone）。"""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str) and value:
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def is_activity_description_present(
    rows: Sequence[ActivityDescriptionRow] | None,
) -> bool:
    """Activity Description スロットの present 判定を返す。"""
    if not rows:
        return False

    for row in rows:
        description = str(row.get("description") or "").strip()
        period_end = parse_iso_datetime(row.get("period_end"))
        if description and period_end is not None:
            return True
    return False


def is_activity_summary_row_present(row: ActivitySummaryRow | None) -> bool:
    """Activity Summary 1スロット分（1h/24h/1w/1m）の present 判定を返す。

    `source_ids` が空の行は ActivitySummaryAgent が下位レコードを1件も要約できず
    「活動なし」定型文だけを書いた行なので、参照可能なコンテキストとしては missing。
    """
    if not row or not row.get("source_ids"):
        return False

    summary = str(row.get("summary") or "").strip()
    period_end = parse_iso_datetime(row.get("period_end"))
    return bool(summary) and period_end is not None


def build_context_density_slot_status(
    *,
    has_long_term_insight: bool,
    has_long_term_facts: bool,
    activity_desc_rows: Sequence[ActivityDescriptionRow] | None,
    summary_1h_row: ActivitySummaryRow | None,
    rows_by_type: Mapping[SummaryType, ActivitySummaryRow | None],
) -> ContextDensitySlotStatus:
    """7スロット分の present/missing 判定を構築する。"""
    return {
        "activity_descriptions": is_activity_description_present(activity_desc_rows),
        "activity_summary_1h": is_activity_summary_row_present(summary_1h_row),
        "activity_summary_24h": is_activity_summary_row_present(
            rows_by_type.get(SUMMARY_TYPE_24H)
        ),
        "activity_summary_1w": is_activity_summary_row_present(
            rows_by_type.get(SUMMARY_TYPE_1W)
        ),
        "activity_summary_1m": is_activity_summary_row_present(
            rows_by_type.get(SUMMARY_TYPE_1M)
        ),
        "long_term_insight": has_long_term_insight,
        "long_term_facts": has_long_term_facts,
    }


def classify_context_density(present_count: int) -> str:
    """present スロット数からコンテキスト密度を low/medium/high に分類する。"""
    slot_count = len(CONTEXT_DENSITY_SLOT_ORDER)
    if present_count < 0 or present_count > slot_count:
        raise ValueError(
            f"present_count must be within 0..{slot_count}: {present_count}"
        )
    if present_count <= CONTEXT_DENSITY_LOW_MAX_PRESENT:
        return "low"
    if present_count <= CONTEXT_DENSITY_MEDIUM_MAX_PRESENT:
        return "medium"
    return "high"


def build_context_density_signal(
    *,
    density: str,
    present_count: int,
    slot_status: ContextDensitySlotStatus,
) -> str:
    """プロンプト投入用の Context Density Signal テキストを構築する。"""
    expected_slot_keys = {slot_key for slot_key, _ in CONTEXT_DENSITY_SLOT_ORDER}
    actual_slot_keys = set(slot_status.keys())
    if actual_slot_keys != expected_slot_keys:
        missing_keys = sorted(expected_slot_keys - actual_slot_keys)
        unexpected_keys = sorted(actual_slot_keys - expected_slot_keys)
        raise ValueError(
            "slot_status keys mismatch: "
            f"missing={missing_keys}, unexpected={unexpected_keys}"
        )

    lines = [
        f"context_density: {density}",
        f"present_count: {present_count}/{len(CONTEXT_DENSITY_SLOT_ORDER)}",
        "slot_status:",
    ]
    for slot_key, label in CONTEXT_DENSITY_SLOT_ORDER:
        status = "present" if slot_status[slot_key] else "missing"
        lines.append(f"- {label}: {status}")
    return "\n".join(lines)


def format_ended_ago(reference_time: datetime, period_end: datetime) -> str:
    """基準時刻から period_end までの経過時間を `19h (68400s)` 形式で返す。"""
    delta_seconds = int((reference_time - period_end).total_seconds())
    if delta_seconds < 0:
        delta_seconds = 0

    if delta_seconds < MINUTES_FORMAT_MAX_SECONDS:
        minutes = delta_seconds // SECONDS_PER_MINUTE
        human = f"{minutes}m"
    elif delta_seconds < HOURS_FORMAT_MAX_SECONDS:
        hours = delta_seconds // SECONDS_PER_HOUR
        human = f"{hours}h"
    else:
        days = delta_seconds // SECONDS_PER_DAY
        human = f"{days}d"

    return f"{human} ({delta_seconds}s)"


def build_recent_activity_summaries_24h_1w_1m(
    *,
    reference_time: datetime,
    rows_by_type: Mapping[SummaryType, ActivitySummaryRow | None],
) -> str:
    """24h/1w/1m の Activity summary をプロンプト投入用に整形する。

    present 判定は Context Availability と同じ `is_activity_summary_row_present`。
    スロットが missing なのに本文だけ「活動なし」の定型文を載せる、という食い違いを作らない。
    """
    lines: list[str] = [
        f"Reference time: {describe_local_time(reference_time, local_zone_name())}"
    ]

    for summary_type in SUMMARY_TYPES_24H_1W_1M:
        row = rows_by_type.get(summary_type)
        pe_dt = parse_iso_datetime(row.get("period_end")) if row else None
        if row is None or pe_dt is None or not is_activity_summary_row_present(row):
            lines.append(f"- [{summary_type}] MISSING (no summary available)")
            continue

        summary = str(row.get("summary") or "").strip()
        ps = describe_utc_timestamp(row["period_start"])
        pe = describe_local_time(pe_dt, None)
        ended_ago = format_ended_ago(reference_time, pe_dt)
        lines.append(
            f"- [{summary_type}] period: {ps} .. {pe} | ended_ago: {ended_ago} | summary: {summary}"
        )

    return "\n".join(lines)
