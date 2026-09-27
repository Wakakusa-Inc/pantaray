"""1 回の THINK が決めたツール呼び出し列に、実行前に step identity を割り当てる。

バッチ K 件は K 個の logical step を消費する。``step_number`` は宣言順に ``n..n+K-1``、
``short_step_id`` は 1 件目が直前 THINK と同じ local step（``S-n-TOOL``）で、2 件目以降は
scope のカウンタを進めて ``S-(n+1)-TOOL``… とする。``upsert_history_entry`` が同一
``short_step_id`` の行を削除置換するため、兄弟呼び出しが同じ ID を持つと履歴が失われる。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from pantaray_agents.agents.action_agent.runtime.models.tool_call import ToolCallModel
from pantaray_agents.agents.action_agent.runtime.state import ActionAgentState
from pantaray_agents.agents.action_agent.tools import ToolDefinition
from pantaray_agents.schema.action_tool_call import ActionToolCallOrigin
from pantaray_agents.schema.agent.action import StepType

from .. import common


@dataclass(frozen=True, slots=True)
class PendingCall:
    """実行前に解決済みのツール呼び出し 1 件。"""

    call: ToolCallModel
    tool_def: ToolDefinition
    step_note: str
    origin: ActionToolCallOrigin | None


@dataclass(frozen=True, slots=True)
class ToolCallSlot:
    """バッチ内 1 呼び出しが占める logical step。"""

    call: ToolCallModel
    tool_def: ToolDefinition
    step_note: str
    step_number: int
    scope_handle: str
    local_step_number: int
    short_step_id: str
    origin: ActionToolCallOrigin | None

    @property
    def tool_id(self) -> str:
        return self.tool_def.tool_id


def allocate_tool_call_slots(
    state: ActionAgentState,
    *,
    calls: Sequence[PendingCall],
) -> tuple[ToolCallSlot, ...]:
    """宣言順に step_number と short_step_id を確定する。"""

    if not calls:
        raise ValueError("a tool call batch must contain at least one call.")

    base_step_number = state["step"]
    inference = common.infer_tool_short_step_id_from_previous_supervisor_think(
        state,
        default_scope_handle=common.SUPERVISOR_SCOPE_HANDLE,
    )
    head_local_step_number, head_short_step_id = _head_step_identity(
        state, inference=inference
    )
    slots: list[ToolCallSlot] = []
    assigned_short_step_ids: set[str] = set()
    for index, pending in enumerate(calls):
        if index == 0:
            local_step_number = head_local_step_number
            short_step_id = head_short_step_id
        else:
            local_step_number = common.get_or_increment_local_step_number(
                state, inference.scope_handle
            )
            short_step_id = common.build_short_step_id(
                inference.scope_handle,
                local_step_number,
                StepType.TOOL_EXECUTION,
            )
        if short_step_id in assigned_short_step_ids:
            # 同一 short_step_id は履歴上の同じ行を指すため、後勝ちで兄弟が消える。
            raise ValueError(
                f"tool call batch produced a duplicate short_step_id: {short_step_id!r}"
            )
        assigned_short_step_ids.add(short_step_id)
        slots.append(
            ToolCallSlot(
                call=pending.call,
                tool_def=pending.tool_def,
                step_note=pending.step_note,
                origin=pending.origin,
                step_number=base_step_number + index,
                scope_handle=inference.scope_handle,
                local_step_number=local_step_number,
                short_step_id=short_step_id,
            )
        )
    return tuple(slots)


def _head_step_identity(
    state: ActionAgentState,
    *,
    inference: common.ToolShortStepIdInference,
) -> tuple[int, str]:
    """バッチ先頭が占める History Ref を決める。

    THINK 直後の実行なら、直前 THINK と同じ local step（``S-n-THINK`` と ``S-n-TOOL``）。
    残バッチを再開したときの先頭は違う: 直前 THINK 由来の History Ref は、既に logical step
    を消費した兄弟呼び出しのものだからだ。消費済みの件数をオフセットとして足すことで、
    採番当時に先頭へ割り当てられていた番号へそのまま戻る。

    - クラッシュ後の残バッチ: オフセット分ずれた未使用の番号を取り、完了済みの兄弟の行を
      ``upsert_history_entry`` で置き換えてしまうのを避ける。
    - 承認 pause からの再開: pause 行は logical step を消費していないので、オフセットは
      pause 行自身を指し、同じ行へ決着する。
    - ToolValidationError の修復ループ: 直前 THINK が同じ行に上書きされ、オフセットは 0 に
      戻るため、再試行は従来どおり同じ TOOL 行を置き換える。
    """

    offset = _consumed_sibling_calls(state, scope_handle=inference.scope_handle)
    if offset == 0:
        return inference.local_step_number, inference.short_step_id
    local_step_number = inference.local_step_number + offset
    return local_step_number, common.build_short_step_id(
        inference.scope_handle, local_step_number, StepType.TOOL_EXECUTION
    )


def _consumed_sibling_calls(state: ActionAgentState, *, scope_handle: str) -> int:
    """直前 THINK 以降に既に logical step を消費した呼び出しの件数。

    THINK 行はバッチ先頭と同じ ``step_number`` を持つ（``executing.py`` は永続化のあと
    ``state["step"]`` を進めない）ので、差分がそのまま消費済み件数になる。
    """

    phase = common.require_active_action_phase(state)
    for entry in reversed(common.get_history_for_scope(state, scope_handle)):
        if entry.get("phase") != phase:
            continue
        if entry.get("step_type") != StepType.LLM_OUTPUT:
            continue
        think_step_number = entry.get("step_number")
        if not isinstance(think_step_number, int):
            return 0
        return max(state["step"] - think_step_number, 0)
    return 0


def call_timeout_seconds(slot: ToolCallSlot) -> float | None:
    """呼び出し 1 件に許す実行時間（秒）。ツール定義が宣言した値をそのまま使う。"""

    timeout_ms = slot.tool_def.execution_policy.default_timeout_ms
    return None if timeout_ms is None else timeout_ms / 1000


__all__ = [
    "PendingCall",
    "ToolCallSlot",
    "allocate_tool_call_slots",
    "call_timeout_seconds",
]
