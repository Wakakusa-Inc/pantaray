"""Pure runtime-state reset for a durable follow-up USER turn."""

from __future__ import annotations

import copy
from collections.abc import MutableMapping
from typing import cast

from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState


def reset_state_for_new_user_turn(
    state: ActionAgentState,
    *,
    started_at: str,
) -> ActionAgentState:
    """Return a reset continuation state without projecting the durable USER."""

    reset = copy.deepcopy(state)
    reset["phase"] = "init"
    reset["status"] = "processing"
    reset["started_at"] = started_at
    reset["updated_at"] = started_at
    reset["next_action"] = None
    reset["final_output"] = None
    reset["errors"] = []
    reset["chunks_sent"] = 0
    reset["run_authority"] = "authoritative"
    reset["skip_persist"] = False
    reset["superseded_reason"] = None
    reset["superseded_at"] = None
    mutable_state = cast(MutableMapping[str, object], reset)
    for field_name in (
        "pending_approval_request",
        "current_approval_blockers",
        "supervisor_pending_final_answer",
        "supervisor_memory_draft",
        "manifest_id",
        "execution_session_id",
        "execution_network_policy",
        "action_temp_dir",
        "app_runtime_python",
        "read_access_scope",
        "cancel_check_consecutive_failures",
        "cancel_check_first_failure_at",
        "cancel_check_last_failure_at",
    ):
        mutable_state.pop(field_name, None)
    reset["goal_conversations"] = {}
    # 新しい USER turn は legacy 行を parent-only へ正規化する。退役キーを残すと
    # 退役 checkpoint と判定されて継続できなくなる。
    cast(MutableMapping[str, object], reset["context"]).pop("use_goal_workers", None)
    return reset


__all__ = ["reset_state_for_new_user_turn"]
