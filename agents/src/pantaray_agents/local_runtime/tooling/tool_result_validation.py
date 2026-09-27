from __future__ import annotations

import math
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

from jsonschema import Draft7Validator, ValidationError  # type: ignore[import-untyped]

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.schema.tool_result import (
    UnprojectedToolOutput,
    serialize_json_tool_output,
)

if TYPE_CHECKING:
    from .tool_result_finalization import FinalizedToolOutput

TOOL_OUTPUT_MAX_NESTING_DEPTH = 100


class ToolOutputValidationError(RuntimeError):
    """A tool returned data outside the runtime output contract."""

    tool_invocation_id: str | None
    finalized_output: FinalizedToolOutput | None

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.tool_invocation_id = None
        self.finalized_output = None


def validate_tool_output_representation(output: object) -> UnprojectedToolOutput:
    if isinstance(output, bytes):
        return output
    _validate_json_value(output)
    validated = cast(JSONValue, output)
    try:
        serialize_json_tool_output(validated)
    except (OverflowError, RecursionError, TypeError, ValueError) as exc:
        raise ToolOutputValidationError(
            "tool output must be serializable finite JSON or bytes"
        ) from exc
    return validated


def validate_successful_tool_output(
    *,
    tool_id: str,
    output: object,
    output_schema: Mapping[str, JSONValue] | None,
) -> None:
    validated = validate_tool_output_representation(output)
    if isinstance(validated, bytes):
        return
    if output_schema is None:
        raise ToolOutputValidationError(
            f"tool {tool_id} has no output schema for successful JSON output"
        )
    try:
        Draft7Validator(output_schema).validate(validated)
    except ValidationError as exc:
        path = ".".join(str(part) for part in exc.absolute_path)
        location = f" at {path}" if path else ""
        validator = str(exc.validator) if exc.validator is not None else "unknown"
        raise ToolOutputValidationError(
            f"tool {tool_id} output does not match its schema{location} "
            f"(validator={validator})"
        ) from None


def _validate_json_value(root: object) -> None:
    stack: list[tuple[object, int, bool]] = [(root, 0, False)]
    active_container_ids: set[int] = set()
    while stack:
        value, depth, leaving = stack.pop()
        if leaving:
            active_container_ids.remove(id(value))
            continue
        if value is None or isinstance(value, (str, bool, int)):
            continue
        if isinstance(value, float):
            if math.isfinite(value):
                continue
            raise ToolOutputValidationError(
                "tool output must be finite JSON or bytes; non-finite number found"
            )
        if not isinstance(value, (list, dict)):
            raise ToolOutputValidationError("tool output must be finite JSON or bytes")
        if depth >= TOOL_OUTPUT_MAX_NESTING_DEPTH:
            raise ToolOutputValidationError(
                "tool output exceeds the maximum JSON nesting depth "
                f"of {TOOL_OUTPUT_MAX_NESTING_DEPTH}"
            )
        container_id = id(value)
        if container_id in active_container_ids:
            raise ToolOutputValidationError("tool output JSON must not contain cycles")
        active_container_ids.add(container_id)
        stack.append((value, depth, True))
        if isinstance(value, list):
            stack.extend((item, depth + 1, False) for item in reversed(value))
            continue
        for key in value:
            if not isinstance(key, str):
                raise ToolOutputValidationError("tool output JSON keys must be strings")
        stack.extend(
            (item, depth + 1, False) for item in reversed(tuple(value.values()))
        )


__all__ = [
    "ToolOutputValidationError",
    "TOOL_OUTPUT_MAX_NESTING_DEPTH",
    "validate_successful_tool_output",
    "validate_tool_output_representation",
]
