"""Goal and insight formatter mixin."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.utils.local_time import describe_utc_timestamp


class GoalFormattingMixin:
    def build_insight_text(
        self,
        long_term: Mapping[str, JSONValue] | None,
        short_term_rows: Sequence[Mapping[str, JSONValue]],
    ) -> str:
        texts: list[str] = []
        if long_term:
            lt_brief = long_term.get("insight_profile_brief")
            lt_full = long_term.get("long_term_insight_data")
            if lt_brief:
                texts.append(f"[Long-term (brief)]\n{lt_brief}")
            elif lt_full:
                texts.append(f"[Long-term]\n{lt_full}")
        if short_term_rows:
            lines = []
            for row in short_term_rows[:5]:
                created = describe_utc_timestamp(str(row["created_at"]))
                content = row.get("short_term_insight_data", "")
                lines.append(f"- [{created}] {content}")
            texts.append("[Short-term]\n" + "\n".join(lines))
        return "\n\n".join(texts) if texts else "(No insight information)"
