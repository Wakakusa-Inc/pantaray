"""退役した Action orchestration mode の checkpoint 判定。"""

from __future__ import annotations

from collections.abc import Mapping

from pantaray_agents.action_status import ACTION_TERMINAL_STATUSES
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState

_RETIRED_PLANNING_PHASE = "planning"


def is_retired_orchestration_checkpoint(checkpoint_state: ActionAgentState) -> bool:
    """Goal Worker mode / mandatory planning phase の継続 checkpoint かを判定する。

    どちらも production の新規実行からは到達しないため、まだ実行を継続できる
    checkpoint だけを typed な resume 拒否の対象にする。
    """

    if (
        checkpoint_state.get("run_authority") == "superseded"
        or checkpoint_state.get("skip_persist")
        or checkpoint_state.get("status") in ACTION_TERMINAL_STATUSES
        or checkpoint_state.get("final_output")
    ):
        return False
    return (
        has_retired_goal_worker_mode(checkpoint_state["context"])
        or checkpoint_state.get("phase") == _RETIRED_PLANNING_PHASE
    )


def has_retired_goal_worker_mode(context: Mapping[str, object]) -> bool:
    """永続 context の退役 use_goal_workers フラグを読む。

    このキーは live な ActionAgentContext からは退役済みで、DB に残りうる legacy
    行を読むためだけに参照する。そのため型ではなく raw mapping として扱う。

    False だけが「単一 ReAct として継続してよい legacy 行」を表す。True と不正値は
    どちらも Goal Worker mode の残骸なので fail-close で退役扱いにする。
    """

    raw_mode = context.get("use_goal_workers")
    return raw_mode is not None and raw_mode is not False


__all__ = [
    "has_retired_goal_worker_mode",
    "is_retired_orchestration_checkpoint",
]
