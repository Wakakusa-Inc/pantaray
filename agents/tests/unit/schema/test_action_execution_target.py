from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.schema.agent.action import (
    ActionAgentRequest,
    ActionUserMessageInput,
)


def _request_fields() -> dict[str, object]:
    return {
        "user_step_id": "user-step-1",
        "user_step_number": 1,
        "user_step_local_step_number": 1,
        "user_step_short_id": "S-1-USER",
        "user_step_created_at": "2026-08-16T00:00:00Z",
        "user_message": ActionUserMessageInput(
            message_id="message-1",
            content="Run the Action",
        ),
    }


def test_action_agent_request_uses_scratch_execution_target() -> None:
    request = ActionAgentRequest(
        user_id="user-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        **_request_fields(),
        execution_target={"kind": "scratch"},
    )

    assert request.execution_target.kind == "scratch"


def test_action_agent_request_rejects_non_scratch_execution_target() -> None:
    with pytest.raises(ValidationError):
        ActionAgentRequest(
            user_id="user-1",
            suggestion_id="suggestion-1",
            action_id="action-1",
            **_request_fields(),
            execution_target={"kind": "manifest", "manifest_id": "manifest-1"},
        )
