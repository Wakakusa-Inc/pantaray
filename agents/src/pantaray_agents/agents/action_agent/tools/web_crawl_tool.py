"""web_crawl ツール定義。"""

from __future__ import annotations

from .base import (
    InputSpec,
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    field_spec,
    tool_execution_policy,
)
from .web_content_validation import validate_web_crawl_args

WEB_CRAWL_TOOL = ToolDefinition.from_spec(
    ToolSpec(
        tool_id="web_crawl",
        name="Web Crawl",
        description=(
            "Crawl outward from one starting URL to collect content across nearby "
            "pages in the same site area. Use this when one exact page is not enough."
        ),
        guide=ToolGuideSpec(
            what=(
                "Use this to gather content across several related pages under one "
                "site section or documentation area."
            ),
            when=(
                "Use when one page is not enough and the relevant information is "
                "likely spread across nearby pages."
            ),
            pitfalls=(
                "Start from a narrow section URL, not a broad homepage when possible. "
                "Use instructions only to describe what pages or information the "
                "crawler should prioritize. This tool returns crawled content, not "
                "a final answer."
            ),
        ),
        execution_policy=tool_execution_policy(
            intent_class="network_access",
            default_timeout_ms=60_000,
        ),
        input_spec=InputSpec(
            fields=(
                field_spec(
                    name="url",
                    schema={
                        "type": "string",
                        "minLength": 1,
                        "format": "uri",
                        "pattern": r"^https?://\S+$",
                        "description": (
                            "Starting URL for the cloud crawl wrapper. This app blocks "
                            "obvious local/internal forms, and the cloud wrapper "
                            "enforces the final fetch policy."
                        ),
                    },
                    required=True,
                    prompt_type="string",
                    description=(
                        "Starting URL for the cloud crawl wrapper. This app blocks "
                        "obvious local/internal forms, and the cloud wrapper "
                        "enforces the final fetch policy."
                    ),
                    llm_order=10,
                ),
                field_spec(
                    name="instructions",
                    schema={
                        "type": "string",
                        "minLength": 1,
                        "pattern": r"\S",
                        "description": (
                            "Optional natural-language crawl instructions. Use this "
                            "to tell the crawler what pages or topics to prioritize "
                            "within the site area."
                        ),
                    },
                    required=False,
                    prompt_type="string",
                    description=(
                        "Optional natural-language instructions that narrow what the "
                        "crawler should look for."
                    ),
                    llm_order=20,
                ),
            )
        ),
        output_schema={
            "type": "object",
            "properties": {
                "base_url": {"type": "string"},
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "raw_content": {"type": "string"},
                        },
                        "required": ["url", "raw_content"],
                        "additionalProperties": False,
                    },
                },
                "response_time": {"type": "number"},
                "meta": {
                    "type": "object",
                    "properties": {
                        "request_id": {"type": "string"},
                        "upstream_provider": {"type": "string"},
                        "profile_id": {"type": "string"},
                        "outcome": {
                            "type": "string",
                            "enum": ["complete", "no_results", "partial_results"],
                        },
                        "upstream_request_id": {"type": "string"},
                        "suggested_action": {"type": "string"},
                    },
                    "required": [
                        "request_id",
                        "upstream_provider",
                        "profile_id",
                        "outcome",
                    ],
                    "additionalProperties": False,
                },
                "error": {
                    "type": "object",
                    "properties": {
                        "error_type": {"type": "string"},
                        "error_code": {"type": "string"},
                        "error_message": {"type": "string"},
                        "error_details": {"type": "object"},
                        "severity": {"type": "string"},
                        "metadata": {"type": "null"},
                    },
                    "required": [
                        "error_type",
                        "error_code",
                        "error_message",
                        "error_details",
                        "severity",
                        "metadata",
                    ],
                    "additionalProperties": False,
                },
            },
            "required": ["results"],
            "additionalProperties": False,
        },
        runtime_config={
            "max_retries": 3,
        },
        pre_validate_args=validate_web_crawl_args,
    )
)
