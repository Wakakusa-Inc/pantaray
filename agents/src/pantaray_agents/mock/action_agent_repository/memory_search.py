"""Mock memory_search の本番境界に合わせた小さな helper。"""

from __future__ import annotations

from datetime import UTC, datetime

from pantaray_agents.agents.action_agent.services.memory_search.common import (
    broad_like_keywords,
    expand_memory_query,
    first_matching_keyword,
    make_snippet,
    score_text_match,
    score_time_hint,
)
from pantaray_agents.local_runtime.memory_catalog.search_policy import (
    MEMORY_SEARCH_FOCUS_SOURCES,
)
from pantaray_agents.local_runtime.memory_references import build_memory_key
from pantaray_agents.repositories.action_support.memory_search_helpers import (
    MEMORY_SEARCH_MAX_LIMIT,
    MEMORY_SEARCH_MAX_TIME_HINT_RADIUS_HOURS,
)
from pantaray_agents.utils.strict_numbers import is_strict_int
from pantaray_agents.utils.timestamps import parse_iso8601_utc

from ..mock_action_agent_repository_types import SourceOptionsPayload

MOCK_MEMORY_KEY_SOURCES = {
    "activity_description": "activity_log",
    "activity_summary": "activity_summary",
    "short_term_insight": "short_term_insight",
    "long_term_insight": "long_term_insight",
    "facts": "fact",
}


def memory_search_sources_for_focus(focus: str) -> tuple[str, ...]:
    return MEMORY_SEARCH_FOCUS_SOURCES[focus]


def mock_memory_search_keywords(query: str) -> list[str]:
    return [
        keyword.casefold()
        for keyword in broad_like_keywords(expand_memory_query(query))
    ]


def mock_memory_search_text_score(*, text: str, query: str) -> float:
    return score_text_match(
        text=text,
        expanded_query=expand_memory_query(query),
        fts_hit=False,
    )


def mock_memory_search_snippet(*, text: str, query: str) -> str:
    keywords = broad_like_keywords(expand_memory_query(query))
    return make_snippet(
        text,
        needle=first_matching_keyword(text, keywords),
    )


def mock_memory_key_for_source(*, source: str, record_id: str) -> str | None:
    memory_source = MOCK_MEMORY_KEY_SOURCES.get(source)
    if memory_source is None or not record_id:
        return None
    return build_memory_key(source=memory_source, record_id=record_id)


def validate_mock_memory_search_request(
    *,
    query: str,
    focus: str,
    time_hint: SourceOptionsPayload | None,
    limit: int,
) -> str | None:
    if not isinstance(query, str) or not query.strip():
        return "memory_search: query is required."
    if focus not in MEMORY_SEARCH_FOCUS_SOURCES:
        return f"memory_search: unsupported focus: {focus}"
    if not is_strict_int(limit) or limit <= 0:
        return "memory_search: limit must be a positive integer."
    if limit > MEMORY_SEARCH_MAX_LIMIT:
        return f"memory_search: limit must be <= {MEMORY_SEARCH_MAX_LIMIT}."
    if time_hint is None:
        return None
    if not isinstance(time_hint, dict):
        return "memory_search: time_hint must be an object."
    center = time_hint.get("center")
    radius_hours = time_hint.get("radius_hours")
    if (center is None) != (radius_hours is None):
        return "memory_search: time_hint.center and time_hint.radius_hours must be provided together."
    if center is not None and parse_mock_datetime(center) is None:
        return "memory_search: time_hint.center must be an ISO8601 string."
    if radius_hours is not None and (
        not is_strict_int(radius_hours) or radius_hours <= 0
    ):
        return "memory_search: time_hint.radius_hours must be a positive integer."
    if (
        is_strict_int(radius_hours)
        and radius_hours > MEMORY_SEARCH_MAX_TIME_HINT_RADIUS_HOURS
    ):
        return (
            "memory_search: time_hint.radius_hours must be <= "
            f"{MEMORY_SEARCH_MAX_TIME_HINT_RADIUS_HOURS}."
        )
    return None


def mock_time_hint_score(
    *,
    value: object,
    center: datetime | None,
    radius_hours: int | None,
) -> float:
    return score_time_hint(value=value, center=center, radius_hours=radius_hours)


def parse_mock_datetime(value: object) -> datetime | None:
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return None
        return value.astimezone(UTC)
    if isinstance(value, str) and value:
        try:
            return parse_iso8601_utc(value)
        except ValueError:
            return None
    return None
