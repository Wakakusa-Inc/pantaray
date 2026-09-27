from __future__ import annotations

from collections.abc import Mapping

from pantaray_agents.agents.action_agent.tools import APPLY_PATCH_TOOL
from pantaray_agents.agents.action_agent.tools.base import schema_to_plain_json
from pantaray_agents.local_runtime.tooling.brokering.broker_protocol import (
    ApplyPatchToolOutput,
    apply_patch_tool_output_json_schema,
)


def test_apply_patch_public_output_schema_uses_broker_protocol_schema() -> None:
    assert (
        schema_to_plain_json(APPLY_PATCH_TOOL.output_schema)
        == apply_patch_tool_output_json_schema()
    )


def test_apply_patch_public_output_schema_includes_error_feedback_fields() -> None:
    schema = APPLY_PATCH_TOOL.output_schema
    properties = schema.get("properties")
    assert isinstance(properties, Mapping)
    assert "diff" in properties
    assert "error" in properties
    assert "warnings" not in properties

    error_payload = ApplyPatchToolOutput(
        status="error",
        applied_paths=["todo.txt"],
        error={
            "type": "PatchApplyError",
            "message": "structured patch could not be applied.",
            "code": "PATCH_CONTEXT_NOT_FOUND",
            "llm_feedback": "Re-read the target file.",
            "exit_code": None,
        },
    )
    assert error_payload.error is not None
    assert error_payload.error.llm_feedback == "Re-read the target file."


def test_apply_patch_public_output_schema_accepts_needs_read() -> None:
    payload = ApplyPatchToolOutput(
        status="needs_read",
        applied_paths=[],
        path="todo.txt",
        patch_applied=False,
        read_scope="target_windows",
        file_truncated=True,
        text="",
        windows=[
            {
                "start_line": 10,
                "end_line": 20,
                "match_reason": "exact_old_lines_match",
                "text": "old line\n",
            }
        ],
        file_sha256="abc123",
        llm_feedback="Rebuild the patch from the returned window text.",
    )

    assert payload.status == "needs_read"
    assert payload.patch_applied is False
    assert payload.windows is not None
    assert payload.windows[0].text == "old line\n"


def test_apply_patch_input_schema_requires_structured_changes() -> None:
    schema = schema_to_plain_json(APPLY_PATCH_TOOL.input_schema)
    assert isinstance(schema, dict)
    properties = schema.get("properties")
    assert isinstance(properties, dict)
    assert "changes" in properties
    assert "patch" not in properties
    assert schema.get("required") == ["changes"]
    changes = properties["changes"]
    assert isinstance(changes, dict)
    serialized_changes = str(changes)
    assert "before_lines" in serialized_changes
    assert "after_lines" in serialized_changes
