from __future__ import annotations

from typing import cast

import pytest

from pantaray_agents.agents.action_agent.runtime.handlers.nodes.common import (
    append_history_entry,
)
from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    create_initial_state,
)
from pantaray_agents.agents.action_agent.runtime.state.context import (
    ensure_context,
    get_context_view,
)
from pantaray_agents.schema.agent.action import StepType


def _make_state() -> ActionAgentState:
    return create_initial_state(
        user_id="user-test",
        suggestion_id="suggestion-test",
        action_id="action-test",
        started_at="2026-03-10T00:00:00+00:00",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )


def test_get_context_view_raises_on_non_dict_context() -> None:
    state = cast(ActionAgentState, {**_make_state(), "context": "broken"})

    with pytest.raises(ValueError, match="context must be a dict"):
        get_context_view(state)


def test_ensure_context_raises_on_non_dict_context() -> None:
    state = cast(ActionAgentState, {**_make_state(), "context": ["broken"]})

    with pytest.raises(ValueError, match="context must be a dict"):
        ensure_context(state)


def test_append_history_entry_replaces_same_logical_history_ref() -> None:
    state = _make_state()
    base_entry = {
        "step_id": "pending-step",
        "step_number": 1,
        "phase": "executing",
        "step_type": StepType.TOOL_EXECUTION,
        "summary": "awaiting approval",
        "tool_id": "bash",
        "started_at": "2026-03-10T00:00:01+00:00",
        "completed_at": "2026-03-10T00:00:02+00:00",
        "output": {"kind": "approval_required"},
        "short_step_id": "G1-1-TOOL",
    }
    append_history_entry(state, scope_handle="G1", entry=base_entry)
    append_history_entry(
        state,
        scope_handle="G1",
        entry={
            **base_entry,
            "step_id": "completed-step",
            "summary": "executed",
            "output": {"status": "success"},
        },
    )

    assert state["history_by_scope"]["G1"] == [
        {
            **base_entry,
            "step_id": "completed-step",
            "summary": "executed",
            "output": {"status": "success"},
        }
    ]
