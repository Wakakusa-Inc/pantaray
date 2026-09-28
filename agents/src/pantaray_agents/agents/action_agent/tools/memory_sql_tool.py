"""memory_sql ツール定義。"""

from __future__ import annotations

from typing import get_args

from pantaray_agents.agents.action_agent.services.memory_sql import (
    DEFAULT_MEMORY_SQL_LIMIT,
    MAX_MEMORY_SQL_LIMIT,
)
from pantaray_agents.local_runtime.activity_summary_schedule import SummaryType

from .base import (
    InputSpec,
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    field_spec,
    tool_execution_policy,
)

_SCALAR_JSON_SCHEMA = {
    "anyOf": [
        {"type": "string"},
        {"type": "number"},
        {"type": "boolean"},
        {"type": "null"},
    ]
}

_TABLE_GUIDE = "\n".join(
    [
        "Readable memory tables:",
        "- agent_suggestions: suggestion records; key columns suggestion_id, user_id, answer, status, created_at, updated_at.",
        "- agent_actions: executed action results; key columns action_id, suggestion_id, user_id, final_output, status, created_at, updated_at.",
        "- agent_insights: short-term insight rows; key columns insight_id, source_activity_summary_id, short_term_insight_data, status, created_at, updated_at.",
        "- agent_facts: structured fact generation rows; key columns fact_id, user_id, facts_profile_brief, structured_fact_sha256, status, created_at, updated_at.",
        "- activity_logs: time-series activity descriptions; key columns log_id, user_id, period_start, period_end, description, status. "
        "period_start/period_end label the 15-minute job window that wrote the row, not the time the activity was observed; the activity "
        "is usually observed before period_start, and further before when recording stopped or the job was delayed. When a question "
        "needs the exact time something was observed rather than the rows of a window, use memory_search, whose source_records "
        "results carry observed_at.",
        "- activity_summaries: aggregated activity summaries; key columns summary_id, summary_type, period_start, period_end, summary, status. "
        f"summary_type is one of {', '.join(get_args(SummaryType))}.",
        "status is the state of the job that wrote the row (processing, success, error, canceled, timeout; agent_actions also queued). "
        "success marks rows that finished normally; error and canceled rows have also finished, so when counting finished work, decide "
        "from each table's statuses which ones count.",
        "Time columns hold UTC ISO8601 strings ending in Z. For the user's local date use date(col, 'localtime'); to filter by local times, convert the boundaries to UTC first.",
    ]
)

MEMORY_SQL_TOOL = ToolDefinition.from_spec(
    ToolSpec(
        tool_id="memory_sql",
        name="Memory SQL",
        description=(
            "Run a read-only SQLite SELECT against memory-related local tables. "
            "Use this to strictly filter, order, or count rows of the memory "
            "tables by time range, source type, IDs, or neighboring rows."
        ),
        guide=ToolGuideSpec(
            what=(
                "Use this to inspect memory with SQL when precise filtering, "
                "ordering, aggregation, joins, or neighboring-row lookup is useful.\n\n"
                "Accepted query shape:\n"
                "- A single read-only SELECT statement.\n"
                "- WITH clauses are allowed only when the final statement is SELECT.\n"
                "- Use ? placeholders for dynamic values and provide values through params.\n"
                "- The executor applies the current action's memory scope automatically.\n\n"
                + _TABLE_GUIDE
            ),
            when=(
                "Use when rows of the readable memory tables must be strictly "
                "filtered by time range or type, ordered, counted or totaled, joined, "
                "or looked up by ID, status, or neighboring rows, for example every "
                "activity description in a time range or the project that took "
                "the most time last week. When the question also names a topic, find "
                "candidates with memory_search and its time_hint first. It can "
                "also follow up on IDs or timestamps that memory_search returned."
            ),
            pitfalls=(
                "Only SELECT / WITH ... SELECT is accepted. Do not use PRAGMA, "
                "INSERT, UPDATE, DELETE, DDL, ATTACH, temp tables, multiple "
                "statements, or tables outside the documented memory allowlist. "
                "Do not add account-scope authorization filters; the executor "
                "applies the action's memory scope automatically. These tables do "
                "not include source records, agent experience, or long-term insight "
                "fragments, so an empty result does not mean nothing is remembered. "
                "Use memory_search to find memories by words or meaning when no "
                "structural filter "
                "applies, and get_memory_reference for explicit fragment links."
            ),
        ),
        execution_policy=tool_execution_policy(
            intent_class="read_only",
            default_timeout_ms=30_000,
        ),
        input_spec=InputSpec(
            fields=(
                field_spec(
                    name="sql",
                    schema={"type": "string", "minLength": 1},
                    required=True,
                    prompt_type="string",
                    description=(
                        "Single read-only SELECT statement.\n"
                        "- WITH ... SELECT is allowed.\n"
                        "- Use ? placeholders with params for dynamic values.\n"
                        "- Do not include multiple statements, PRAGMA, writes, DDL, "
                        "ATTACH, or manual account-scope authorization filters."
                    ),
                    llm_order=10,
                ),
                field_spec(
                    name="params",
                    schema={
                        "type": "array",
                        "items": _SCALAR_JSON_SCHEMA,
                        "maxItems": 50,
                    },
                    prompt_type="array",
                    description=(
                        "Optional scalar parameters for ? placeholders.\n"
                        "- Provide values in placeholder order.\n"
                        "- Values must be string, number, boolean, or null."
                    ),
                    llm_order=20,
                ),
                field_spec(
                    name="limit",
                    schema={
                        "type": "integer",
                        "minimum": 1,
                        "maximum": MAX_MEMORY_SQL_LIMIT,
                    },
                    prompt_type="integer",
                    description=(
                        "Optional max rows to return.\n"
                        f"- Default: {DEFAULT_MEMORY_SQL_LIMIT}.\n"
                        f"- Maximum: {MAX_MEMORY_SQL_LIMIT}."
                    ),
                    llm_order=30,
                ),
            )
        ),
        output_schema={
            "type": "object",
            "properties": {
                "columns": {"type": "array", "items": {"type": "string"}},
                "rows": {"type": "array", "items": {"type": "object"}},
                "row_count": {"type": "integer"},
                "truncated": {"type": "boolean"},
                "notes": {"type": "array", "items": {"type": "string"}},
            },
            "required": ["columns", "rows", "row_count", "truncated", "notes"],
            "additionalProperties": False,
        },
        runtime_config={
            "default_limit": DEFAULT_MEMORY_SQL_LIMIT,
            "max_limit": MAX_MEMORY_SQL_LIMIT,
        },
    )
)

__all__ = ["MEMORY_SQL_TOOL"]
