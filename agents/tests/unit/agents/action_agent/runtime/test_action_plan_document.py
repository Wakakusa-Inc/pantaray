from __future__ import annotations

import stat
from collections.abc import Mapping
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from tests.unit.agents.action_agent.fixtures import create_state_token_sink

from pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime.execution import (
    run_validated_tool_impl,
)
from pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime.shared import (
    ToolExecutionActor,
    ToolValidationError,
    UnprojectedToolExecutionResult,
    ValidatedToolArgs,
)
from pantaray_agents.agents.action_agent.runtime.state import (
    ActionAgentState,
    create_initial_state,
)
from pantaray_agents.agents.action_agent.tools import (
    READ_ACTION_PLAN_TOOL,
    SUPERVISOR_SINGLE_REACT_TOOL_IDS,
    TOOL_REGISTRY,
    WRITE_ACTION_PLAN_TOOL,
)
from pantaray_agents.agents.action_agent.tools.base import ToolDefinition
from pantaray_agents.local_runtime.tooling.action_plan_document import (
    ACTION_PLAN_MAX_BYTES,
    ActionPlanTooLargeError,
)
from pantaray_agents.local_runtime.tooling.action_session_temp_paths import (
    resolve_action_storage_paths,
)

USER_ID = "user-1"
ACTION_ID = "action-1"


def _state() -> ActionAgentState:
    return create_initial_state(
        user_id=USER_ID,
        suggestion_id="suggestion-1",
        action_id=ACTION_ID,
        started_at="2026-09-01T00:00:00Z",
        max_steps=10,
        max_tool_steps=10,
        token_budget=None,
    )


def _create_workspace(tmp_path: Path) -> tuple[Path, Path]:
    db_path = tmp_path / "runtime.db"
    workspace = resolve_action_storage_paths(
        db_path=db_path,
        user_id=USER_ID,
        action_id=ACTION_ID,
    ).workspace
    workspace.mkdir(parents=True)
    return db_path, workspace


async def _run_tool(
    tool: ToolDefinition,
    args: ValidatedToolArgs,
    *,
    actor: ToolExecutionActor = "supervisor",
) -> UnprojectedToolExecutionResult:
    state = _state()
    return await run_validated_tool_impl(
        MagicMock(),
        tool,
        args,
        state,
        sink=create_state_token_sink(state),
        runtime=SimpleNamespace(),
        actor=actor,
    )


@pytest.mark.asyncio
async def test_supervisor_plan_tools_use_only_canonical_scratch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, workspace = _create_workspace(tmp_path)
    project_plan = tmp_path / "project" / "plan.md"
    project_plan.parent.mkdir()
    project_plan.write_text("project plan", encoding="utf-8")
    monkeypatch.setattr(
        "pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime."
        "plan_document.read_local_runtime_db_config",
        lambda: (db_path, 1_000),
    )

    content = "# Plan\n\n- verify 🌱\n"
    written = await _run_tool(WRITE_ACTION_PLAN_TOOL, {"content": content})
    present = await _run_tool(READ_ACTION_PLAN_TOOL, {})

    assert written.output == {"status": "written"}
    assert present.output == {"status": "present", "content": content}
    assert stat.S_IMODE((workspace / "plan.md").stat().st_mode) == 0o600
    assert project_plan.read_text(encoding="utf-8") == "project plan"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "args"),
    [
        (READ_ACTION_PLAN_TOOL, {}),
        (WRITE_ACTION_PLAN_TOOL, {"content": "must not be written"}),
    ],
)
async def test_goal_worker_cannot_use_action_plan_tools_before_runtime_io(
    tool: ToolDefinition,
    args: ValidatedToolArgs,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    read_config = MagicMock(side_effect=AssertionError("filesystem boundary reached"))
    monkeypatch.setattr(
        "pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime."
        "plan_document.read_local_runtime_db_config",
        read_config,
    )

    with pytest.raises(ToolValidationError, match="only available to the Supervisor"):
        await _run_tool(tool, args, actor="goal_worker")

    read_config.assert_not_called()


@pytest.mark.asyncio
async def test_saved_oversize_plan_is_not_reported_as_invalid_tool_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db_path, workspace = _create_workspace(tmp_path)
    (workspace / "plan.md").write_bytes(b"x" * (ACTION_PLAN_MAX_BYTES + 1))
    monkeypatch.setattr(
        "pantaray_agents.agents.action_agent.runtime.handlers.tool_runtime."
        "plan_document.read_local_runtime_db_config",
        lambda: (db_path, 1_000),
    )

    with pytest.raises(ActionPlanTooLargeError):
        await _run_tool(READ_ACTION_PLAN_TOOL, {})


def test_action_plan_tools_have_no_path_input_and_are_parent_only() -> None:
    read_properties = READ_ACTION_PLAN_TOOL.input_schema["properties"]
    write_properties = WRITE_ACTION_PLAN_TOOL.input_schema["properties"]
    assert isinstance(read_properties, Mapping) and not read_properties
    assert isinstance(write_properties, Mapping) and set(write_properties) == {
        "content"
    }
    for tool_id in ("read_action_plan", "write_action_plan"):
        assert tool_id in TOOL_REGISTRY
        assert tool_id in SUPERVISOR_SINGLE_REACT_TOOL_IDS
