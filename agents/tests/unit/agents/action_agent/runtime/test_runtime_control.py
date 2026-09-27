from __future__ import annotations

from types import SimpleNamespace

import pytest

from pantaray_agents.action_status import (
    ACTION_FAILURE_CODE_RESUME_APPROVAL_STATE_INVALID,
)
from pantaray_agents.agents.action_agent.runtime.state import create_initial_state
from pantaray_agents.application.action.approval_resume_restoration import (
    normalize_approval_resume_state,
    restore_pending_tool_request_for_approval_resume,
)
from pantaray_agents.application.action.resume_service import ResumeStateError


def _load_pending_approval_session(_user_id: str, _tool_request_id: str):
    return SimpleNamespace(status="pending", approval_session_id="approval-1")


def _now() -> str:
    return "2026-03-26T00:00:00Z"


def _base_state() -> dict:
    return create_initial_state(
        user_id="user-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        started_at="2026-03-20T10:00:00Z",
        max_steps=20,
        max_tool_steps=20,
        token_budget=None,
    )


def test_normalize_approval_resume_state_raises_only_for_validation_errors() -> None:
    state = _base_state()
    state["pending_approval_request"] = {"owner": "supervisor"}

    with pytest.raises(ResumeStateError) as exc_info:
        normalize_approval_resume_state(
            state,
            load_approval_session_by_request=_load_pending_approval_session,
            now_provider=_now,
        )

    assert (
        exc_info.value.failure_code == ACTION_FAILURE_CODE_RESUME_APPROVAL_STATE_INVALID
    )


def test_restore_approved_tool_request_raises_only_for_validation_errors() -> None:
    state = _base_state()
    state["pending_approval_request"] = {"owner": "goal_worker"}

    with pytest.raises(ResumeStateError) as exc_info:
        restore_pending_tool_request_for_approval_resume(state, now_provider=_now)

    assert (
        exc_info.value.failure_code == ACTION_FAILURE_CODE_RESUME_APPROVAL_STATE_INVALID
    )
