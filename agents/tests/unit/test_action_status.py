from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.action_status import (
    ACTION_FAILURE_CODE_RESUME_CHECKPOINT_INVALID,
    ACTION_STATUS_ERROR,
    ACTION_STATUS_SUCCESS,
    build_action_timeout_failure,
    build_finalize_action_terminal_command,
    build_resume_failure,
    derive_action_phase,
    parse_stored_suggestion_user_reaction,
    require_stored_suggestion_user_reaction,
)
from pantaray_agents.schema.agent.action import ActionRunResult


def test_build_finalize_action_terminal_command_requires_success_output() -> None:
    with pytest.raises(
        ValueError,
        match="FinalizeActionTerminalCommand: success requires final_output",
    ):
        _ = build_finalize_action_terminal_command(
            process_completed_event_id="evt-1",
            suggestion_id="sug-1",
            user_id="user-1",
            command_id="cmd-1",
            process_id="proc-1",
            action_id="act-1",
            accepted_at="2026-03-21T00:00:00Z",
            completed_at="2026-03-21T00:01:00Z",
            action_status=ACTION_STATUS_SUCCESS,
        )


def test_build_finalize_action_terminal_command_uses_failure_defaults() -> None:
    failure = build_action_timeout_failure()

    command = build_finalize_action_terminal_command(
        process_completed_event_id="evt-2",
        suggestion_id="sug-2",
        user_id="user-2",
        command_id="cmd-2",
        process_id="proc-2",
        action_id="act-2",
        accepted_at="2026-03-21T00:00:00Z",
        completed_at="2026-03-21T00:01:00Z",
        action_status=ACTION_STATUS_ERROR,
        failure=failure,
    )

    assert command.failure_code == failure.failure_code
    assert command.failure_stage == failure.failure_stage
    assert command.failure_message_public == failure.failure_message_public
    assert command.final_output is None
    assert command.process_completed_payload == {
        "data": {
            "kind": "action",
            "process_id": "proc-2",
            "suggestion_id": "sug-2",
            "action_id": "act-2",
            "command_id": "cmd-2",
            "status": ACTION_STATUS_ERROR,
            "completed_at": "2026-03-21T00:01:00.000000Z",
            "failure_code": failure.failure_code,
            "failure_stage": failure.failure_stage,
            "failure_message_public": failure.failure_message_public,
        },
        "meta": {
            "kind": "action",
            "process_id": "proc-2",
            "suggestion_id": "sug-2",
            "action_id": "act-2",
            "command_id": "cmd-2",
            "failure_code": failure.failure_code,
        },
    }


def test_build_resume_failure_uses_public_failed_message() -> None:
    failure = build_resume_failure(
        failure_code=ACTION_FAILURE_CODE_RESUME_CHECKPOINT_INVALID
    )

    assert failure.failure_code == ACTION_FAILURE_CODE_RESUME_CHECKPOINT_INVALID
    assert failure.failure_stage == "resume_failed"
    assert failure.failure_message_public == "Action execution failed."


def test_build_finalize_action_terminal_command_builds_success_payload() -> None:
    command = build_finalize_action_terminal_command(
        process_completed_event_id="evt-3",
        suggestion_id="sug-3",
        user_id="user-3",
        command_id="cmd-3",
        process_id="proc-3",
        action_id="act-3",
        accepted_at="2026-03-21T00:00:00Z",
        completed_at="2026-03-21T00:01:00Z",
        action_status=ACTION_STATUS_SUCCESS,
        final_output="done",
    )

    assert command.process_completed_payload == {
        "data": {
            "kind": "action",
            "process_id": "proc-3",
            "suggestion_id": "sug-3",
            "action_id": "act-3",
            "command_id": "cmd-3",
            "status": ACTION_STATUS_SUCCESS,
            "completed_at": "2026-03-21T00:01:00.000000Z",
            "final_output": "done",
        },
        "meta": {
            "kind": "action",
            "process_id": "proc-3",
            "suggestion_id": "sug-3",
            "action_id": "act-3",
            "command_id": "cmd-3",
        },
    }


def test_build_finalize_action_terminal_command_includes_structured_error_payload() -> (
    None
):
    command = build_finalize_action_terminal_command(
        process_completed_event_id="evt-err",
        suggestion_id="sug-err",
        user_id="user-err",
        command_id="cmd-err",
        process_id="proc-err",
        action_id="act-err",
        accepted_at="2026-03-21T00:00:00Z",
        completed_at="2026-03-21T00:01:00Z",
        action_status=ACTION_STATUS_ERROR,
        failure_code="ACTION_LLM_RESPONSE_ERROR",
        failure_stage="running_failed",
        failure_message_public="Action execution failed.",
        error_payload={
            "error_type": "llm_api_error",
            "error_code": "ACTION_LLM_RESPONSE_ERROR",
            "error_message": "blocked by upstream",
            "error_details": {
                "request_id": "req-1",
                "profile_id": "action.planning",
            },
            "severity": "error",
        },
    )

    assert command.process_completed_payload["data"]["error"] == {
        "error_type": "llm_api_error",
        "error_code": "ACTION_LLM_RESPONSE_ERROR",
        "error_message": "blocked by upstream",
        "error_details": {
            "request_id": "req-1",
            "profile_id": "action.planning",
        },
        "severity": "error",
    }


def test_build_finalize_action_terminal_command_normalizes_timestamp_to_utc_z() -> None:
    command = build_finalize_action_terminal_command(
        process_completed_event_id="evt-4",
        suggestion_id="sug-4",
        user_id="user-4",
        command_id="cmd-4",
        process_id="proc-4",
        action_id="act-4",
        accepted_at="2026-03-21T09:00:00+09:00",
        completed_at="2026-03-21T09:01:02+09:00",
        action_status=ACTION_STATUS_SUCCESS,
        final_output="done",
    )

    assert command.accepted_at == "2026-03-21T00:00:00.000000Z"
    assert command.completed_at == "2026-03-21T00:01:02.000000Z"
    assert command.process_completed_payload["data"]["completed_at"] == (
        "2026-03-21T00:01:02.000000Z"
    )


def test_build_finalize_action_terminal_command_rejects_bool_step_counters() -> None:
    with pytest.raises(
        ValueError,
        match=(
            "FinalizeActionTerminalCommand: total_steps "
            "must be a non-negative integer or null"
        ),
    ):
        _ = build_finalize_action_terminal_command(
            process_completed_event_id="evt-5",
            suggestion_id="sug-5",
            user_id="user-5",
            command_id="cmd-5",
            process_id="proc-5",
            action_id="act-5",
            accepted_at="2026-03-21T00:00:00Z",
            completed_at="2026-03-21T00:01:00Z",
            action_status=ACTION_STATUS_SUCCESS,
            final_output="done",
            total_steps=True,
        )


def test_action_run_result_rejects_timeout_status() -> None:
    with pytest.raises(ValidationError):
        _ = ActionRunResult(
            action_id="act-1",
            suggestion_id="sug-1",
            user_id="user-1",
            completed_at="2026-03-21T00:01:00Z",
            status="timeout",
            final_output="",
            action_failure_code="ACTION_PROCESSING_TIMEOUT",
            failure_stage="running_failed",
            failure_message_public="Action execution failed.",
        )


def test_derive_action_phase_accepts_current_start_lane_statuses() -> None:
    queued_phase = derive_action_phase(
        user_reaction="accepted",
        action_status="idle",
        process_status="enqueued",
        job_status="queued",
    )
    assert queued_phase == "accepted_pending_start"

    running_phase = derive_action_phase(
        user_reaction="accepted",
        action_status="idle",
        process_status="running",
        job_status="running",
    )
    assert running_phase == "accepted_pending_start"


@pytest.mark.parametrize(
    ("process_status", "job_status"),
    [
        ("enqueued", "running"),
        ("running", "queued"),
    ],
)
def test_derive_action_phase_rejects_inconsistent_start_lane_pairs(
    process_status: str,
    job_status: str,
) -> None:
    phase = derive_action_phase(
        user_reaction="accepted",
        action_status="idle",
        process_status=process_status,
        job_status=job_status,
    )

    assert phase == "idle"


def test_parse_stored_suggestion_user_reaction_tolerates_stale_values() -> None:
    assert parse_stored_suggestion_user_reaction(" Accepted ") == "accepted"
    assert parse_stored_suggestion_user_reaction(" rejected ") == "rejected"
    assert parse_stored_suggestion_user_reaction("ignored") is None
    assert parse_stored_suggestion_user_reaction("pending") is None
    assert parse_stored_suggestion_user_reaction("unexpected") is None


def test_require_stored_suggestion_user_reaction_rejects_stale_values() -> None:
    assert require_stored_suggestion_user_reaction(" rejected ") == "rejected"
    with pytest.raises(ValueError, match="Unsupported suggestion user reaction"):
        require_stored_suggestion_user_reaction("ignored")


def test_derive_action_phase_treats_stale_reaction_as_unreacted() -> None:
    phase = derive_action_phase(
        user_reaction="ignored",
        action_status="idle",
        process_status=None,
        job_status=None,
    )

    assert phase == "idle"


def test_derive_action_phase_normalizes_user_reaction() -> None:
    phase = derive_action_phase(
        user_reaction=" Accepted ",
        action_status=" idle ",
        process_status=" enqueued ",
        job_status=" queued ",
    )

    assert phase == "accepted_pending_start"
