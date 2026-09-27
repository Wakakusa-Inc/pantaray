from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.steps.counters import (
    CounterInvariantError,
    increment_llm_steps_taken,
    increment_local_step_counter,
    increment_tool_steps_taken,
    require_local_step_counters_map,
    require_scope_handle,
    sync_steps_taken,
)


def test_sync_steps_taken_rejects_non_int_counter_value() -> None:
    """不正型カウンタを 0 に丸めず、例外で不変条件違反を顕在化する。"""
    state = {
        "llm_steps_taken": "2",
        "tool_steps_taken": 1,
        "steps_taken": 0,
    }

    with pytest.raises(CounterInvariantError, match="llm_steps_taken"):
        sync_steps_taken(state)  # type: ignore[arg-type]

    assert state["llm_steps_taken"] == "2"
    assert state["steps_taken"] == 0


def test_sync_steps_taken_rejects_negative_counter_value() -> None:
    """負数カウンタを許容せず、状態破損を明示的に停止する。"""
    state = {
        "llm_steps_taken": 0,
        "tool_steps_taken": -1,
        "steps_taken": 0,
    }

    with pytest.raises(CounterInvariantError, match="tool_steps_taken"):
        sync_steps_taken(state)  # type: ignore[arg-type]


def test_increment_llm_steps_taken_rejects_corrupted_existing_counter() -> None:
    """既存カウンタが壊れている場合も増分時に丸めず失敗する。"""
    state = {
        "llm_steps_taken": "3",
        "tool_steps_taken": 1,
        "steps_taken": 0,
    }

    with pytest.raises(CounterInvariantError, match="llm_steps_taken"):
        increment_llm_steps_taken(state)  # type: ignore[arg-type]


def test_increment_tool_steps_taken_rejects_invalid_increment() -> None:
    """不正な増分値を許容しない。"""
    state = {
        "llm_steps_taken": 0,
        "tool_steps_taken": 0,
        "steps_taken": 0,
    }

    with pytest.raises(CounterInvariantError, match="increment"):
        increment_tool_steps_taken(state, increment=-1)  # type: ignore[arg-type]


def test_sync_steps_taken_rejects_missing_counter_field() -> None:
    """必須カウンタ欠損は不変条件違反として即停止する。"""
    state = {
        "llm_steps_taken": 1,
        "steps_taken": 0,
    }

    with pytest.raises(CounterInvariantError, match="tool_steps_taken is missing"):
        sync_steps_taken(state)  # type: ignore[arg-type]


def test_increment_local_step_counter_initializes_scope_counter() -> None:
    """local_step_counters 未設定時は初回採番を 1 として開始する。"""
    state = {"context": {}}

    assert increment_local_step_counter(state, scope_handle="S") == 1  # type: ignore[arg-type]
    assert state["context"]["local_step_counters"]["S"] == 1


def test_increment_local_step_counter_rejects_invalid_existing_counter() -> None:
    """scope の既存値が 1 未満なら即停止する。"""
    state = {"context": {"local_step_counters": {"S": 0}}}

    with pytest.raises(CounterInvariantError, match="context.local_step_counters"):
        increment_local_step_counter(state, scope_handle="S")  # type: ignore[arg-type]


def test_require_local_step_counters_map_rejects_invalid_scope() -> None:
    """不正な scope_handle は正規化前に拒否する。"""
    with pytest.raises(CounterInvariantError, match="scope_handle"):
        require_local_step_counters_map(
            field_name="context.local_step_counters",
            value={"invalid-scope": 1},
        )


def test_require_scope_handle_rejects_non_string() -> None:
    """scope_handle は文字列のみ許可する。"""
    with pytest.raises(CounterInvariantError, match="scope handle string"):
        require_scope_handle(field_name="scope_handle", value=1)
