"""web_extract ツール定義。"""

from __future__ import annotations

from .base import (
    InputSpec,
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    field_spec,
    tool_execution_policy,
)
from .web_content_validation import validate_web_extract_args

WEB_EXTRACT_TOOL = ToolDefinition.from_spec(
    ToolSpec(
        tool_id="web_extract",
        name="Web Extract",
        description=(
            "Extract the main body content from specific web pages that you already "
            "know. Accepts up to 5 exact URLs and returns normalized page text."
        ),
        guide=ToolGuideSpec(
            what=(
                "Use this to read the main content of exact pages after you have "
                "identified the right URLs."
            ),
            when=(
                "Use after web_search or when the user already provided concrete page "
                "URLs and you want the actual page content."
            ),
            pitfalls=(
                "Pass direct page URLs, not homepages unless the homepage itself is "
                "the target. Use query only to express what content matters for "
                "reranking. This tool returns extracted content, not a final answer."
            ),
        ),
        execution_policy=tool_execution_policy(
            intent_class="network_access",
            default_timeout_ms=60_000,
        ),
        input_spec=InputSpec(
            fields=(
                field_spec(
                    name="urls",
                    schema={
                        "type": "array",
                        "minItems": 1,
                        "maxItems": 5,
                        "items": {
                            "type": "string",
                            "minLength": 1,
                            "format": "uri",
                            "pattern": r"^https?://\S+$",
                        },
                        "description": (
                            "Page URLs to extract via the cloud search wrapper (max 5). "
                            "This app blocks obvious local/internal forms, "
                            "and the cloud wrapper enforces the final fetch policy."
                        ),
                    },
                    required=True,
                    prompt_type="string[]",
                    description=(
                        "Page URLs to extract via the cloud search wrapper (max 5). "
                        "This app blocks obvious local/internal forms, "
                        "and the cloud wrapper enforces the final fetch policy."
                    ),
                    llm_order=10,
                ),
                field_spec(
                    name="query",
                    schema={
                        "type": "string",
                        "minLength": 1,
                        "pattern": r"\S",
                        "description": (
                            "Optional intent string used only to rerank extracted "
                            "content chunks. Describe what information matters in "
                            "the extracted pages."
                        ),
                    },
                    required=False,
                    prompt_type="string",
                    description=(
                        "Optional intent string used only to rerank extracted "
                        "content chunks by relevance."
                    ),
                    llm_order=20,
                ),
            )
        ),
        output_schema={
            "type": "object",
            "properties": {
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
                "failed_results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "url": {"type": "string"},
                            "error": {"type": "string"},
                        },
                        "required": ["url", "error"],
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
            "required": ["results", "failed_results"],
            "additionalProperties": False,
        },
        runtime_config={
            "max_retries": 3,
        },
        pre_validate_args=validate_web_extract_args,
    )
)
