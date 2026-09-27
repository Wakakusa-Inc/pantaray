from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime.request_identity import (
    resolve_tool_request_id,
    set_resumed_tool_request_id,
)
from pantaray_agents.agents.action_agent.runtime.state import create_initial_state


def _base_state() -> dict[str, object]:
    state = create_initial_state(
        user_id="user-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        started_at="2026-03-30T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )
    state["step"] = 3
    return state


def test_resolve_tool_request_id_allocates_monotonic_index_per_step() -> None:
    state = _base_state()

    first_request_id = resolve_tool_request_id(state=state, step_id="tool-step-a")
    second_request_id = resolve_tool_request_id(state=state, step_id="tool-step-b")

    assert first_request_id == "action-1:tool-step-a:1"
    assert second_request_id == "action-1:tool-step-b:2"
    assert state["context"]["approval_request_counters"] == {"3": 2}


def test_resolve_tool_request_id_reuses_resume_request_id_once() -> None:
    state = _base_state()
    set_resumed_tool_request_id(state=state, tool_request_id="request-resume-1")

    resumed_request_id = resolve_tool_request_id(state=state, step_id="tool-step-a")
    fresh_request_id = resolve_tool_request_id(state=state, step_id="tool-step-b")

    assert resumed_request_id == "request-resume-1"
    assert fresh_request_id == "action-1:tool-step-b:1"


def test_resolve_tool_request_id_rejects_bool_step() -> None:
    state = _base_state()
    state["step"] = True

    with pytest.raises(
        RuntimeError,
        match="tool request identity requires state.step >= 1",
    ):
        _ = resolve_tool_request_id(state=state, step_id="tool-step-a")


def test_resolve_tool_request_id_rejects_bool_counter_values() -> None:
    state = _base_state()
    state["context"]["approval_request_counters"] = {"3": True}

    with pytest.raises(
        RuntimeError,
        match="approval_request_counters must be a string->int map",
    ):
        _ = resolve_tool_request_id(state=state, step_id="tool-step-a")
