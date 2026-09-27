from __future__ import annotations

import math

import pytest

from pantaray_agents.local_runtime.tooling.tool_result_validation import (
    TOOL_OUTPUT_MAX_NESTING_DEPTH,
    ToolOutputValidationError,
    validate_successful_tool_output,
    validate_tool_output_representation,
)

_OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def test_successful_json_output_must_match_declared_schema() -> None:
    validate_successful_tool_output(
        tool_id="test",
        output={"ok": True},
        output_schema=_OBJECT_SCHEMA,
    )

    with pytest.raises(ToolOutputValidationError, match="does not match"):
        validate_successful_tool_output(
            tool_id="test",
            output={"unexpected": True},
            output_schema=_OBJECT_SCHEMA,
        )


def test_schema_error_does_not_echo_rejected_output_value() -> None:
    secret = "private-output-value"
    with pytest.raises(ToolOutputValidationError) as raised:
        validate_successful_tool_output(
            tool_id="test",
            output={"ok": secret},
            output_schema=_OBJECT_SCHEMA,
        )

    assert secret not in str(raised.value)


def test_bytes_are_an_explicit_non_json_output() -> None:
    validate_successful_tool_output(
        tool_id="test",
        output=b"raw bytes",
        output_schema=_OBJECT_SCHEMA,
    )


def test_non_json_non_bytes_representation_is_rejected_before_storage() -> None:
    with pytest.raises(ToolOutputValidationError, match="finite JSON or bytes"):
        validate_tool_output_representation({"unsupported"})


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf))
def test_non_finite_numbers_are_rejected(value: float) -> None:
    with pytest.raises(ToolOutputValidationError, match="finite JSON or bytes"):
        validate_successful_tool_output(
            tool_id="test",
            output={"value": value},
            output_schema={"type": "object"},
        )


def test_cyclic_json_is_rejected_as_a_contract_error() -> None:
    output: list[object] = []
    output.append(output)

    with pytest.raises(ToolOutputValidationError, match="must not contain cycles"):
        validate_tool_output_representation(output)


def test_excessive_json_nesting_is_rejected_before_serialization() -> None:
    output: object = "leaf"
    for _ in range(TOOL_OUTPUT_MAX_NESTING_DEPTH + 1):
        output = [output]

    with pytest.raises(ToolOutputValidationError, match="maximum JSON nesting"):
        validate_tool_output_representation(output)
