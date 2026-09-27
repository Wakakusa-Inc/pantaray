"""Supervisor 向けの LLM-facing ツールスキーマ生成。

Supervisor が呼ぶすべてのツールには、履歴に残す `step_note` を必須引数として
ここで注入する。個々の ToolSpec は `step_note` を知らない。`step_note` は
ハンドラ／ブローカーへは渡さず、`split_step_note` で剥がして履歴の要約に使う。

引数名が `note` ではなく `step_note` なのは、`link_memory.note`（2 つの記憶の
関係を書く既存の必須引数）と意味が衝突するため。
"""

from __future__ import annotations

from collections.abc import Mapping

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_llm.contracts.tool_use import LlmToolDefinition

from .base import ToolDefinition, ToolPolicyValidationError

STEP_NOTE_ARG = "step_note"
STEP_NOTE_MAX_LENGTH = 200
STEP_NOTE_DESCRIPTION = (
    "In 1-3 sentences: what you observed, why, and what this call does. "
    "Written for someone reading the history later. "
    f"1-{STEP_NOTE_MAX_LENGTH} characters."
)


def build_native_action_tools(
    registry: Mapping[str, ToolDefinition],
) -> tuple[LlmToolDefinition, ...]:
    return tuple(
        LlmToolDefinition(
            name=tool.tool_id,
            description=tool.prompt_contract.description or tool.description,
            parameters=_with_step_note(
                tool.tool_id,
                tool.build_validation_input_schema(),
            ),
        )
        for tool in registry.values()
    )


def split_step_note(
    arguments: Mapping[str, JSONValue],
) -> tuple[str, dict[str, JSONValue]]:
    """`step_note` を検証して取り出し、ハンドラ向け引数と分離する。

    Raises:
        ToolPolicyValidationError: `step_note` が欠落・非文字列・空・長すぎる場合。
    """

    raw_note = arguments.get(STEP_NOTE_ARG)
    if raw_note is None:
        raise _step_note_error(
            f"Missing required arg `{STEP_NOTE_ARG}`. {STEP_NOTE_DESCRIPTION}"
        )
    if not isinstance(raw_note, str):
        raise _step_note_error(f"`{STEP_NOTE_ARG}` must be a string.")
    note = raw_note.strip()
    if not note:
        raise _step_note_error(
            f"`{STEP_NOTE_ARG}` must not be empty. {STEP_NOTE_DESCRIPTION}"
        )
    if len(note) > STEP_NOTE_MAX_LENGTH:
        raise _step_note_error(
            f"`{STEP_NOTE_ARG}` must be at most {STEP_NOTE_MAX_LENGTH} characters; "
            f"got {len(note)}."
        )
    return note, {
        name: value for name, value in arguments.items() if name != STEP_NOTE_ARG
    }


def _step_note_error(message: str) -> ToolPolicyValidationError:
    return ToolPolicyValidationError(
        message,
        details={
            "path": [STEP_NOTE_ARG],
            "message": message,
            "metadata": {"max_length": STEP_NOTE_MAX_LENGTH},
        },
    )


def _with_step_note(
    tool_id: str,
    schema: dict[str, JSONValue],
) -> dict[str, JSONValue]:
    properties = schema.get("properties")
    required = schema.get("required")
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise ValueError(
            f"Tool '{tool_id}' input schema must expose top-level properties and "
            "required so the supervisor step note can be injected."
        )
    if STEP_NOTE_ARG in properties:
        raise ValueError(
            f"Tool '{tool_id}' already defines '{STEP_NOTE_ARG}'; "
            "the supervisor step note argument must stay unique."
        )
    injected = dict(schema)
    injected["properties"] = {
        STEP_NOTE_ARG: {
            "type": "string",
            "minLength": 1,
            "maxLength": STEP_NOTE_MAX_LENGTH,
            "description": STEP_NOTE_DESCRIPTION,
        },
        **properties,
    }
    injected["required"] = [STEP_NOTE_ARG, *required]
    return injected


__all__ = [
    "STEP_NOTE_ARG",
    "STEP_NOTE_DESCRIPTION",
    "STEP_NOTE_MAX_LENGTH",
    "build_native_action_tools",
    "split_step_note",
]
