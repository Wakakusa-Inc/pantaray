"""ActionAgent のステップカウンタ更新ロジックを集約する。"""

from __future__ import annotations

from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentContext,
    ActionAgentState,
)
from pantaray_agents.schema.agent.action_history import (
    GOAL_SCOPE_RE,
    SUPERVISOR_SCOPE_HANDLE,
)

# 1 回の LLM / Tool 実行で増える標準増分。
DEFAULT_STEP_INCREMENT = 1


class CounterInvariantError(RuntimeError):
    """ステップカウンタの不変条件違反。"""


def _require_context(state: ActionAgentState) -> ActionAgentContext:
    raw_context = state.get("context")
    if not isinstance(raw_context, dict):
        raise CounterInvariantError(
            "ActionAgent state invariant violated: context must be a dict."
        )
    return raw_context


def _require_non_negative_int(*, field_name: str, value: object) -> int:
    """カウンタ値が 0 以上の int であることを検証する。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CounterInvariantError(
            f"{field_name} must be a non-negative int, got {type(value).__name__}: {value!r}"
        )
    if value < 0:
        raise CounterInvariantError(f"{field_name} must be >= 0, got {value!r}")
    return value


def require_step_counter_value(*, field_name: str, value: object) -> int:
    """任意入力をステップカウンタとして検証する。"""
    return _require_non_negative_int(field_name=field_name, value=value)


def require_runtime_step_number(*, field_name: str, value: object) -> int:
    """runtime 上の論理 step 番号（1 始まり）を厳格検証する。"""
    step_number = _require_non_negative_int(field_name=field_name, value=value)
    if step_number < 1:
        raise CounterInvariantError(f"{field_name} must be >= 1, got {step_number!r}")
    return step_number


def require_scope_handle(*, field_name: str, value: object) -> str:
    """scope_handle（S / G{n}）を厳格検証する。"""
    if not isinstance(value, str):
        raise CounterInvariantError(
            f"{field_name} must be a scope handle string, "
            f"got {type(value).__name__}: {value!r}"
        )
    normalized = value.strip()
    if normalized == SUPERVISOR_SCOPE_HANDLE or GOAL_SCOPE_RE.fullmatch(normalized):
        return normalized
    raise CounterInvariantError(
        f"{field_name} must be '{SUPERVISOR_SCOPE_HANDLE}' or 'G{{n}}' "
        f"(n is a positive integer), got {value!r}"
    )


def require_local_step_counter_value(*, field_name: str, value: object) -> int:
    """local_step_counters の値（1 以上の int）を厳格検証する。"""
    if isinstance(value, bool) or not isinstance(value, int):
        raise CounterInvariantError(
            f"{field_name} must be a positive int, "
            f"got {type(value).__name__}: {value!r}"
        )
    if value < 1:
        raise CounterInvariantError(f"{field_name} must be >= 1, got {value!r}")
    return value


def require_local_step_counters_map(
    *,
    field_name: str,
    value: object,
) -> dict[str, int]:
    """local_step_counters マップを厳格検証する。"""
    if not isinstance(value, dict):
        raise CounterInvariantError(
            f"{field_name} must be a dict[str, int], got {type(value).__name__}: {value!r}"
        )

    normalized: dict[str, int] = {}
    for raw_scope, raw_counter in value.items():
        scope = require_scope_handle(
            field_name=f"{field_name}.scope_handle",
            value=raw_scope,
        )
        counter = require_local_step_counter_value(
            field_name=f"{field_name}[{scope}]",
            value=raw_counter,
        )
        if scope in normalized:
            raise CounterInvariantError(
                f"{field_name} contains duplicate scope_handle after normalization: {scope!r}"
            )
        normalized[scope] = counter
    return normalized


def increment_local_step_counter(
    state: ActionAgentState,
    *,
    scope_handle: str,
) -> int:
    """scope_handle ごとの local_step_counter を +1 して返す。"""
    normalized_scope = require_scope_handle(
        field_name="scope_handle",
        value=scope_handle,
    )

    context = _require_context(state)

    raw_counters = context.get("local_step_counters")
    counters: dict[str, int]
    if raw_counters is None:
        counters = {}
    else:
        counters = require_local_step_counters_map(
            field_name="context.local_step_counters",
            value=raw_counters,
        )

    next_value = counters.get(normalized_scope, 0) + 1
    counters[normalized_scope] = next_value
    context["local_step_counters"] = counters
    state["context"] = context
    return next_value


def get_llm_steps_taken(state: ActionAgentState) -> int:
    """state から llm_steps_taken を厳格に取得する。"""
    if "llm_steps_taken" not in state:
        raise CounterInvariantError("llm_steps_taken is missing in state")
    return _require_non_negative_int(
        field_name="llm_steps_taken",
        value=state["llm_steps_taken"],
    )


def get_tool_steps_taken(state: ActionAgentState) -> int:
    """state から tool_steps_taken を厳格に取得する。"""
    if "tool_steps_taken" not in state:
        raise CounterInvariantError("tool_steps_taken is missing in state")
    return _require_non_negative_int(
        field_name="tool_steps_taken",
        value=state["tool_steps_taken"],
    )


def compute_step_counter_delta(
    *,
    field_name: str,
    base_value: object,
    current_value: object,
) -> int:
    """カウンタ差分を計算し、逆行（current < base）を不変条件違反として検出する。"""
    base = _require_non_negative_int(
        field_name=f"base_{field_name}",
        value=base_value,
    )
    current = _require_non_negative_int(
        field_name=field_name,
        value=current_value,
    )
    delta = current - base
    if delta < 0:
        raise CounterInvariantError(
            f"{field_name} regressed: base={base}, current={current}"
        )
    return delta


def sync_steps_taken(state: ActionAgentState) -> None:
    """`steps_taken = llm_steps_taken + tool_steps_taken` を一元的に保証する。"""
    llm_steps_taken = get_llm_steps_taken(state)
    tool_steps_taken = get_tool_steps_taken(state)
    state["llm_steps_taken"] = llm_steps_taken
    state["tool_steps_taken"] = tool_steps_taken
    state["steps_taken"] = llm_steps_taken + tool_steps_taken


def increment_llm_steps_taken(
    state: ActionAgentState,
    *,
    increment: int = DEFAULT_STEP_INCREMENT,
) -> None:
    """LLM ステップ数を増分し、`steps_taken` を同期する。"""
    increment_value = require_step_counter_value(
        field_name="increment",
        value=increment,
    )
    current = get_llm_steps_taken(state)
    state["llm_steps_taken"] = current + increment_value
    sync_steps_taken(state)


def increment_tool_steps_taken(
    state: ActionAgentState,
    *,
    increment: int = DEFAULT_STEP_INCREMENT,
) -> None:
    """Tool ステップ数を増分し、`steps_taken` を同期する。"""
    increment_value = require_step_counter_value(
        field_name="increment",
        value=increment,
    )
    current = get_tool_steps_taken(state)
    state["tool_steps_taken"] = current + increment_value
    sync_steps_taken(state)


__all__ = [
    "compute_step_counter_delta",
    "CounterInvariantError",
    "DEFAULT_STEP_INCREMENT",
    "get_llm_steps_taken",
    "get_tool_steps_taken",
    "increment_llm_steps_taken",
    "increment_local_step_counter",
    "increment_tool_steps_taken",
    "require_local_step_counter_value",
    "require_local_step_counters_map",
    "require_runtime_step_number",
    "require_scope_handle",
    "require_step_counter_value",
    "sync_steps_taken",
]
