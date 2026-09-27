"""Action history の LLM-visible ref と fetch 投影契約。"""

from __future__ import annotations

import re
from typing import Final, TypedDict

from pantaray_agents.schema.agent.action import SHORT_STEP_SUFFIX_PATTERN, StepType
from pantaray_agents.schema.agent.base import JSONValue

SUPERVISOR_SCOPE_HANDLE: Final[str] = "S"
GOAL_SCOPE_PATTERN: Final[str] = r"G[1-9][0-9]*"
POSITIVE_INTEGER_PATTERN: Final[str] = r"[1-9][0-9]*"
SCOPE_HANDLE_PATTERN: Final[str] = (
    rf"(?:{SUPERVISOR_SCOPE_HANDLE}|{GOAL_SCOPE_PATTERN})"
)

GOAL_SCOPE_RE: Final[re.Pattern[str]] = re.compile(rf"^{GOAL_SCOPE_PATTERN}$")
HISTORY_FETCH_MAX_REFS: Final[int] = 20


class HistoryFetchStep(TypedDict):
    """UUID と checkpoint を含まない永続 Action step 投影。"""

    short_step_id: str
    step_number: int
    local_step_number: int
    step_name: str
    step_type: str
    status: str
    user_request_text: str | None
    thinking: str | None
    llm_prompt_text: str | None
    llm_response_text: str | None
    tool_args: dict[str, JSONValue] | None
    tool_output: dict[str, JSONValue] | None
    error: dict[str, JSONValue] | None
    goal_handle: str | None
    started_at: str | None
    completed_at: str | None


def build_short_step_id_pattern(*, suffix_pattern: str) -> str:
    """short_step_id の JSON Schema pattern を構築する。"""

    return (
        rf"^{SCOPE_HANDLE_PATTERN}-{POSITIVE_INTEGER_PATTERN}"
        rf"-(?:{suffix_pattern})$"
    )


def build_short_step_id_capture_pattern(*, suffix_pattern: str) -> str:
    """short_step_id の parse 用 capture pattern を構築する。"""

    return (
        rf"^({SCOPE_HANDLE_PATTERN})-({POSITIVE_INTEGER_PATTERN})-"
        rf"({suffix_pattern})$"
    )


def build_short_step_id_regex(*, suffix_pattern: str) -> re.Pattern[str]:
    """short_step_id の検証用正規表現を構築する。"""

    return re.compile(
        build_short_step_id_capture_pattern(suffix_pattern=suffix_pattern)
    )


HISTORY_FETCH_SHORT_STEP_PATTERN: Final[str] = build_short_step_id_pattern(
    suffix_pattern=SHORT_STEP_SUFFIX_PATTERN
)
HISTORY_FETCH_SHORT_STEP_RE: Final[re.Pattern[str]] = re.compile(
    HISTORY_FETCH_SHORT_STEP_PATTERN
)


def history_fetch_refs_schema() -> dict[str, JSONValue]:
    """選択的かつ bounded な history_fetch 入力schemaを返す。"""

    return {
        "type": "array",
        "description": (
            "One or more displayed short step IDs, such as 'S-1-USER', "
            "'S-2-THINK', or 'G1-3-TOOL'."
        ),
        "items": {
            "type": "string",
            "pattern": HISTORY_FETCH_SHORT_STEP_PATTERN,
        },
        "minItems": 1,
        "maxItems": HISTORY_FETCH_MAX_REFS,
        "uniqueItems": True,
    }


def history_fetch_step_schema() -> dict[str, JSONValue]:
    """USER / THINK / TOOL 共通のfetch出力item schemaを返す。"""

    nullable_text: dict[str, JSONValue] = {"type": ["string", "null"]}
    nullable_object: dict[str, JSONValue] = {
        "type": ["object", "null"],
        "additionalProperties": True,
    }
    properties: dict[str, JSONValue] = {
        "short_step_id": {
            "type": "string",
            "pattern": HISTORY_FETCH_SHORT_STEP_PATTERN,
        },
        "step_number": {"type": "integer", "minimum": 1},
        "local_step_number": {"type": "integer", "minimum": 1},
        "step_name": {"type": "string", "minLength": 1},
        "step_type": {
            "type": "string",
            "enum": [step_type.value for step_type in StepType],
        },
        "status": {
            "type": "string",
            "enum": ["queued", "processing", "success", "error", "timeout"],
        },
        "user_request_text": nullable_text,
        "thinking": nullable_text,
        "llm_prompt_text": nullable_text,
        "llm_response_text": nullable_text,
        "tool_args": nullable_object,
        "tool_output": nullable_object,
        "error": nullable_object,
        "goal_handle": nullable_text,
        "started_at": nullable_text,
        "completed_at": nullable_text,
    }
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


__all__ = [
    "GOAL_SCOPE_PATTERN",
    "GOAL_SCOPE_RE",
    "HISTORY_FETCH_MAX_REFS",
    "HISTORY_FETCH_SHORT_STEP_PATTERN",
    "HISTORY_FETCH_SHORT_STEP_RE",
    "HistoryFetchStep",
    "POSITIVE_INTEGER_PATTERN",
    "SCOPE_HANDLE_PATTERN",
    "SUPERVISOR_SCOPE_HANDLE",
    "build_short_step_id_capture_pattern",
    "build_short_step_id_pattern",
    "build_short_step_id_regex",
    "history_fetch_refs_schema",
    "history_fetch_step_schema",
]
