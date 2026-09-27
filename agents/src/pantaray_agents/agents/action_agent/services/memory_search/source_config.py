from __future__ import annotations

from typing import Literal, TypedDict

type TextSourceStatusPolicy = Literal["exclude_processing", "success_only"]


class TextSearchConfig(TypedDict):
    table: str
    fts_table: str
    id_field: str
    content_field: str
    time_column: str
    order_column: str
    status_policy: TextSourceStatusPolicy


ARTIFACT_SOURCES = frozenset({"long_term_insight", "facts"})

ROW_SEARCH_CONFIG: dict[str, TextSearchConfig] = {
    "suggestions": {
        "table": "agent_suggestions",
        "fts_table": "memory_search_agent_suggestions_fts",
        "id_field": "suggestion_id",
        "content_field": "answer",
        "time_column": "created_at",
        "order_column": "created_at",
        "status_policy": "exclude_processing",
    },
    "actions": {
        "table": "agent_actions",
        "fts_table": "memory_search_agent_actions_fts",
        "id_field": "action_id",
        "content_field": "final_output",
        "time_column": "updated_at",
        "order_column": "updated_at",
        "status_policy": "exclude_processing",
    },
    "short_term_insight": {
        "table": "agent_insights",
        "fts_table": "memory_search_agent_insights_fts",
        "id_field": "insight_id",
        "content_field": "short_term_insight_data",
        "time_column": "updated_at",
        "order_column": "updated_at",
        "status_policy": "success_only",
    },
    "activity_description": {
        "table": "activity_logs",
        "fts_table": "memory_search_activity_logs_fts",
        "id_field": "log_id",
        "content_field": "description",
        "time_column": "period_end",
        "order_column": "period_end",
        "status_policy": "success_only",
    },
    "activity_summary": {
        "table": "activity_summaries",
        "fts_table": "memory_search_activity_summaries_fts",
        "id_field": "summary_id",
        "content_field": "summary",
        "time_column": "period_end",
        "order_column": "period_end",
        "status_policy": "success_only",
    },
}


def text_source_status_clause(config: TextSearchConfig) -> str:
    policy = config["status_policy"]
    if policy == "exclude_processing":
        return "AND rows.status <> 'processing'"
    if policy == "success_only":
        return "AND rows.status = 'success'"
    raise ValueError(f"Unsupported memory_search status policy: {policy}")


def text_source_status_matches(*, source: str, status: object) -> bool:
    config = ROW_SEARCH_CONFIG[source]
    policy = config["status_policy"]
    if policy == "exclude_processing":
        return status is not None and str(status) != "processing"
    if policy == "success_only":
        return str(status) == "success"
    raise ValueError(f"Unsupported memory_search status policy: {policy}")
