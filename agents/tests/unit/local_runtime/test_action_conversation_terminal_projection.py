import json
from dataclasses import replace
from typing import cast

import pytest

from pantaray_agents.action_status import (
    ActionTerminalStatus,
    build_finalize_action_terminal_command,
    derive_action_terminal_failure,
)
from pantaray_agents.local_runtime.action_conversation.repository import (
    ActionConversationIntegrityError,
)
from pantaray_agents.local_runtime.action_conversation.terminal_projection import (
    ActionRunTerminalProjection,
    project_action_run_terminal,
)
from pantaray_agents.local_runtime.runtime.action_logical_run_authority import (
    ActionLogicalRunAuthority,
)
from pantaray_agents.schema.action_conversation import ActionConversationSummary

_COMPLETED_AT = "2026-08-30T00:01:00Z"


def _terminal_authority(
    status: ActionTerminalStatus,
) -> tuple[ActionConversationSummary, ActionLogicalRunAuthority]:
    failure = derive_action_terminal_failure(status)
    command = build_finalize_action_terminal_command(
        process_completed_event_id="event-1",
        suggestion_id="suggestion-1",
        user_id="user-1",
        command_id="command-1",
        process_id="run-1",
        action_id="action-1",
        accepted_at="2026-08-30T00:00:00Z",
        completed_at=_COMPLETED_AT,
        action_status=status,
        final_output="done" if status == "success" else None,
        failure=failure,
        error_payload=None if failure is None else {"private": "trace"},
    )
    payload = dict(command.process_completed_payload["data"])
    payload["persisted_sequence"] = 9
    process_status = {
        "success": "completed",
        "error": "failed",
        "canceled": "canceled",
    }[status]
    return (
        ActionConversationSummary(
            action_id="action-1",
            suggestion_id="suggestion-1",
            approved_suggestion=None,
            status=status,
            latest_run_id="run-1",
            resumable=False,
        ),
        ActionLogicalRunAuthority(
            action_id="action-1",
            root_process_id="run-1",
            root_accepted_sequence=1,
            root_started_at="2026-08-30T00:00:00Z",
            process_status=process_status,
            job_id="job-1",
            job_status=process_status,
            completed_at=_COMPLETED_AT,
            terminal_event_id="event-1",
            terminal_event_payload_json=json.dumps(payload),
        ),
    )


def _project(
    status: ActionTerminalStatus,
    authority: ActionLogicalRunAuthority | None = None,
) -> ActionRunTerminalProjection:
    action, canonical_authority = _terminal_authority(status)
    return project_action_run_terminal(
        user_id="user-1",
        action=action,
        authority=authority or canonical_authority,
    )


def test_projects_success_final_output() -> None:
    result = _project("success")

    assert (result.status, result.completed_at, result.final_output, result.error) == (
        "success",
        _COMPLETED_AT,
        "done",
        None,
    )


@pytest.mark.parametrize("status", ["error", "canceled"])
def test_projects_only_public_terminal_error(status: ActionTerminalStatus) -> None:
    result = _project(status)

    failure = derive_action_terminal_failure(status)
    assert failure is not None and result.error is not None
    assert (
        result.status,
        result.error.code,
        result.error.message,
        result.final_output,
    ) == (
        status,
        failure.failure_code,
        failure.failure_message_public,
        None,
    )
    assert "private" not in result.error.model_dump_json()


def test_rejects_payload_status_mismatched_with_authority() -> None:
    _, authority = _terminal_authority("success")

    with pytest.raises(ActionConversationIntegrityError):
        _project(
            "success",
            replace(
                authority,
                process_status="failed",
                job_status="failed",
            ),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [("action_id", "other-action")],
)
def test_rejects_terminal_authority_identity_mismatch(
    field: str,
    value: str,
) -> None:
    _, authority = _terminal_authority("success")
    changed = replace(authority, action_id=value)

    with pytest.raises(ActionConversationIntegrityError):
        _project("success", changed)


@pytest.mark.parametrize(
    "update",
    [
        {"physical_run_only": True},
        {"status": "error"},
        {"process_id": "other-run"},
        {"persisted_sequence": True},
    ],
)
def test_rejects_corrupt_terminal_payload(update: dict[str, object]) -> None:
    _, authority = _terminal_authority("success")
    payload = json.loads(cast(str, authority.terminal_event_payload_json))
    payload.update(update)

    with pytest.raises(ActionConversationIntegrityError):
        _project(
            "success",
            replace(authority, terminal_event_payload_json=json.dumps(payload)),
        )
