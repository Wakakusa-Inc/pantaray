from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.conversation_service import (
    pause_goal_worker_turn,
    start_goal_worker_turn,
)
from pantaray_agents.agents.action_agent.runtime.models.conversation import (
    GoalConversationStateModel,
)
from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    ActionPhase,
    build_next_action,
    build_pending_approval_request,
    build_tool_call,
    create_initial_state,
)
from pantaray_agents.application.action.resume_errors import ResumeStateError
from pantaray_agents.application.action.resume_routing import (
    graph_route_from_resume_state,
)


def _running_worker_state() -> ActionAgentState:
    state = create_initial_state(
        user_id="user-1",
        suggestion_id="suggestion-1",
        action_id="action-1",
        started_at="2026-07-18T00:00:00Z",
        max_steps=20,
        max_tool_steps=20,
        token_budget=None,
    )
    state["context"]["use_goal_workers"] = True
    state["goal_conversations"] = {
        "G1": start_goal_worker_turn(
            GoalConversationStateModel(goal_id="G1"),
            generation=1,
            started_at="2026-07-18T00:00:01Z",
            targeted=False,
        )
    }
    return state


def test_running_mid_wave_checkpoint_is_rejected_by_parent_only_graph() -> None:
    state = _running_worker_state()

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


def test_paused_worker_without_resumable_tool_is_rejected() -> None:
    state = _running_worker_state()
    state["goal_conversations"] = {
        "G1": pause_goal_worker_turn(state["goal_conversations"]["G1"])
    }

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


def test_worker_mode_checkpoint_without_active_turn_is_rejected() -> None:
    state = _running_worker_state()
    state["goal_conversations"] = {}

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


def test_pending_goal_worker_approval_is_rejected_before_halt() -> None:
    state = _running_worker_state()
    state["pending_approval_request"] = build_pending_approval_request(
        owner="goal_worker",
        tool_id="read",
        args={"path": "/tmp/input.txt"},
        approval_session_id="approval-1",
        tool_request_id="request-1",
        requested_at="2026-07-18T00:00:02Z",
        intent_class="read_local",
        command_summary={"path": "/tmp/input.txt"},
        goal_id="G1",
    )

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


def _planning_supervisor_state() -> ActionAgentState:
    state = _running_worker_state()
    state["context"]["use_goal_workers"] = False
    state["goal_conversations"] = {}
    state["phase"] = "planning"
    return state


def test_planning_checkpoint_with_pending_tool_is_rejected() -> None:
    state = _planning_supervisor_state()
    state["next_action"] = build_next_action(
        tool=build_tool_call(tool_id="memory_search", args={"query": "prior"}),
        decided_at="2026-07-18T00:00:02Z",
    )

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


def test_planning_checkpoint_without_pending_tool_is_rejected() -> None:
    state = _planning_supervisor_state()
    state["next_action"] = None

    with pytest.raises(ResumeStateError, match="parent-only graph"):
        graph_route_from_resume_state(state)


@pytest.mark.parametrize("phase", ("planning", "executing"))
@pytest.mark.parametrize(
    ("run_authority", "skip_persist"),
    (("superseded", False), ("authoritative", True)),
)
def test_non_authoritative_resume_finalizes_before_pending_work(
    phase: ActionPhase,
    run_authority: str,
    skip_persist: bool,
) -> None:
    state = _running_worker_state()
    state["phase"] = phase
    state["run_authority"] = run_authority
    state["skip_persist"] = skip_persist
    state["pending_approval_request"] = build_pending_approval_request(
        owner="supervisor",
        tool_id="memory_search",
        args={"query": "must not execute"},
        approval_session_id="approval-1",
        tool_request_id="request-1",
        requested_at="2026-07-18T00:00:02Z",
        intent_class="process_exec_local",
        command_summary={"query": "must not execute"},
    )
    state["next_action"] = build_next_action(
        tool=build_tool_call(
            tool_id="memory_search",
            args={"query": "must not execute"},
        ),
        decided_at="2026-07-18T00:00:02Z",
    )

    assert graph_route_from_resume_state(state) == "finalize"
