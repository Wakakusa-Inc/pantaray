"""ActionAgentState.context の取得・初期化・copy を扱う共通 helper。

責務:
    - read-only view の取得
    - write path 用 context の確保
    - shallow copy による mutation 用スナップショットの生成

方針:
    - state/context の操作だけを扱い、payload validation は持ち込まない。
    - context や list 要素の型不整合は明示例外で fail-closed にする。
    - copy は shallow copy に統一する。
"""

from __future__ import annotations

from typing import cast

from .types import (
    ActionAgentContext,
    ActionAgentState,
)

_STATE_INVARIANT_CONTEXT_MESSAGE = (
    "ActionAgent state invariant violated: context must be a dict."
)


def get_context_view(state: ActionAgentState) -> ActionAgentContext:
    """state から read-only な context view を返す。"""
    raw_state = cast(dict[str, object], state)
    context = raw_state.get("context")
    if not isinstance(context, dict):
        raise ValueError(_STATE_INVARIANT_CONTEXT_MESSAGE)
    return cast(ActionAgentContext, context)


def require_context(state: ActionAgentState) -> ActionAgentContext:
    """context が dict であることを要求する。"""
    return get_context_view(state)


def ensure_context(state: ActionAgentState) -> ActionAgentContext:
    """write path 用に context を確保して返す。"""
    raw_state = cast(dict[str, object], state)
    context = raw_state.get("context")
    if context is not None:
        if not isinstance(context, dict):
            raise ValueError(_STATE_INVARIANT_CONTEXT_MESSAGE)
        return cast(ActionAgentContext, context)
    new_context = cast(ActionAgentContext, {})
    state["context"] = new_context
    return new_context


def copy_state_with_context(
    state: ActionAgentState,
) -> tuple[ActionAgentState, ActionAgentContext]:
    """state と context の shallow copy を返す。"""
    updated_state = cast(ActionAgentState, dict(state))
    updated_context = cast(ActionAgentContext, dict(get_context_view(state)))
    updated_state["context"] = updated_context
    return updated_state, updated_context


def copy_context(state: ActionAgentState) -> ActionAgentContext:
    """context の shallow copy を返す。"""
    return cast(ActionAgentContext, dict(get_context_view(state)))


__all__ = [
    "copy_context",
    "copy_state_with_context",
    "ensure_context",
    "get_context_view",
    "require_context",
]
