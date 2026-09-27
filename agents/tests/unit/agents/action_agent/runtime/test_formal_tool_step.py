from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.steps.tool import (
    TOOL_STEP_ERROR_MESSAGE_MAX_CHARS,
    build_finalized_tool_step,
    project_tool_step_for_persistence,
)
from pantaray_agents.local_runtime.tooling.tool_result_finalization import (
    FinalizedToolOutput,
)
from pantaray_agents.schema.agent.base import AgentError


def _finalized_output() -> FinalizedToolOutput:
    return FinalizedToolOutput(
        output={"result": "durable"},
        storage_kind="action_file",
        owner_kind="tool_invocation",
        search_text=None,
        stdout_text=None,
        stderr_text=None,
    )


def _error(*, severity: str = "warning", message: str = "failed") -> AgentError:
    return AgentError(
        error_type="tool_execution_error",
        error_code="ACTION_TOOL_FAILED",
        error_message=message,
        error_details={"diagnostic": "full details stay in finalized output"},
        metadata={"private": "not persisted in the error identity"},
        severity=severity,
    )


def test_projection_derives_exact_envelope_and_bounded_error_from_one_result() -> None:
    projection = project_tool_step_for_persistence(
        build_finalized_tool_step(
            status="error",
            output=_finalized_output(),
            error=_error(),
        )
    )

    assert projection.output_json == {
        "schema_version": 1,
        "status": "error",
        "output": {"result": "durable"},
        "output_storage_kind": "action_file",
        "output_owner_kind": "tool_invocation",
    }
    assert projection.error == {
        "error_type": "tool_execution_error",
        "error_code": "ACTION_TOOL_FAILED",
        "error_message": "failed",
        "severity": "warning",
    }


def test_error_identity_truncates_message_without_copying_diagnostics() -> None:
    projection = project_tool_step_for_persistence(
        build_finalized_tool_step(
            status="error",
            output=_finalized_output(),
            error=_error(message="x" * (TOOL_STEP_ERROR_MESSAGE_MAX_CHARS + 1)),
        )
    )

    assert projection.error is not None
    assert len(projection.error["error_message"] or "") == (
        TOOL_STEP_ERROR_MESSAGE_MAX_CHARS
    )
    assert set(projection.error) == {
        "error_type",
        "error_code",
        "error_message",
        "severity",
    }


def test_error_status_requires_error_identity() -> None:
    with pytest.raises(ValueError, match="require a bounded error identity"):
        build_finalized_tool_step(status="error", output=_finalized_output())


def test_processing_status_rejects_error_identity() -> None:
    with pytest.raises(ValueError, match="cannot contain an error"):
        build_finalized_tool_step(
            status="processing",
            output=_finalized_output(),
            error=_error(),
        )


def test_success_status_rejects_fatal_error_identity() -> None:
    with pytest.raises(ValueError, match="only accept non-fatal errors"):
        build_finalized_tool_step(
            status="success",
            output=_finalized_output(),
            error=_error(severity="error"),
        )
