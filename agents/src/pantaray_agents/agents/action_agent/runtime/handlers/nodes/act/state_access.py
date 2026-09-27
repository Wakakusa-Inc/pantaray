"""Typed state readers for Supervisor act execution."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pantaray_agents.agents.action_agent.runtime.models.tool_call import NextActionModel
from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    NextAction,
)
from pantaray_agents.schema.agent.base import JSONValue

type ToolArgsPayload = dict[str, JSONValue]


def latest_state_error_payload(
    state: ActionAgentState,
    *,
    error_code: str,
) -> dict[str, JSONValue]:
    raw_errors = state.get("errors")
    if not isinstance(raw_errors, list):
        raise ValueError("ActionAgent state invariant violated: errors must be a list.")
    for raw_error in reversed(raw_errors):
        if isinstance(raw_error, dict) and raw_error.get("error_code") == error_code:
            return cast("dict[str, JSONValue]", dict(raw_error))
    raise ValueError(
        "ActionAgent state invariant violated: expected state error is missing: "
        f"error_code={error_code}"
    )


def raw_next_action(state: ActionAgentState) -> object:
    """Read checkpoint state before trusting its declared TypedDict shape."""
    raw_state = cast("Mapping[str, object]", state)
    return raw_state.get("next_action")


def canonical_next_action(value: object) -> NextAction | None:
    """Narrow an untrusted checkpoint value to the canonical action model."""
    return value if isinstance(value, NextActionModel) else None


__all__ = [
    "ToolArgsPayload",
    "canonical_next_action",
    "latest_state_error_payload",
    "raw_next_action",
]
