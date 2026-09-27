from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.agents.action_agent.runtime.models.execution_context import (
    execution_context_from_state,
)


def _valid_execution_context_state() -> dict[str, object]:
    return {
        "manifest_id": "manifest-1",
        "execution_session_id": "exec-1",
        "execution_network_policy": "restricted",
        "action_temp_dir": "/tmp/action-1",
        "app_runtime_python": "/usr/bin/python3",
        "read_access_scope": "workspace",
    }


def test_execution_context_from_state_returns_none_when_all_fields_absent() -> None:
    assert execution_context_from_state({"action_id": "action-1"}) is None


def test_execution_context_from_state_normalizes_valid_string_fields() -> None:
    state = _valid_execution_context_state()
    state["manifest_id"] = " manifest-1 "

    execution_context = execution_context_from_state(state)

    assert execution_context is not None
    assert execution_context.manifest_id == "manifest-1"


def test_execution_context_from_state_rejects_blank_present_fields() -> None:
    state = dict.fromkeys(_valid_execution_context_state(), " ")

    with pytest.raises(ValidationError, match="non-empty"):
        execution_context_from_state(state)


def test_execution_context_from_state_rejects_none_present_fields() -> None:
    state = dict.fromkeys(_valid_execution_context_state(), None)

    with pytest.raises(ValidationError, match="manifest_id"):
        execution_context_from_state(state)


def test_execution_context_from_state_rejects_partial_present_fields() -> None:
    state = _valid_execution_context_state()
    state.pop("read_access_scope")

    with pytest.raises(ValidationError, match="read_access_scope"):
        execution_context_from_state(state)


def test_execution_context_from_state_rejects_non_string_present_fields() -> None:
    state = _valid_execution_context_state()
    state["execution_session_id"] = 123

    with pytest.raises(ValidationError, match="execution_session_id"):
        execution_context_from_state(state)
