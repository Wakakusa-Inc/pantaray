from __future__ import annotations

from pathlib import Path

import pytest
from tests.unit.local_runtime.broker_test_support import BROKER_ACTOR_PROCESS_ID

from pantaray_agents.local_runtime.tooling.brokering.broker import (
    BrokerApprovalRequiredError,
    BrokerToolOutcome,
    apply_approval_decision,
    execute_broker_tool,
)
from pantaray_agents.local_runtime.tooling.repository import load_execution_session

from .support import (
    INTEGRATION_APPROVAL_TIMESTAMP,
    ONE_SECOND_MS,
    SEATBELT_SKIP_REASON,
    RuntimeIntegrationTestbed,
    bootstrap_runtime_testbed,
    seatbelt_available,
)

pytestmark = pytest.mark.skipif(not seatbelt_available(), reason=SEATBELT_SKIP_REASON)


async def _bash(
    testbed: RuntimeIntegrationTestbed, *, cwd: Path, command: str
) -> BrokerToolOutcome:
    outcome = await execute_broker_tool(
        db_path=testbed.db_path,
        busy_timeout_ms=ONE_SECOND_MS,
        tool_id="bash",
        user_id="user-1",
        actor_process_id=BROKER_ACTOR_PROCESS_ID,
        manifest_id=testbed.context.manifest_id,
        execution_session_id=testbed.context.execution_session_id,
        tool_request_id="request-outside",
        args={"command": command, "cwd": str(cwd)},
    )
    assert isinstance(outcome, BrokerToolOutcome)
    return outcome


@pytest.mark.asyncio
async def test_approved_outside_cwd_is_writable_only_inside_that_folder(
    tmp_path: Path, outside_temp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    app_data = tmp_path / "app-data"
    app_data.mkdir()
    testbed = bootstrap_runtime_testbed(tmp_path=app_data, monkeypatch=monkeypatch)
    outside = outside_temp_path / "outside"
    outside.mkdir()
    sibling = outside_temp_path / "sibling.txt"
    command = f"echo made > made.txt; echo leak > {sibling} || echo denied"

    session = load_execution_session(
        db_path=testbed.db_path,
        busy_timeout_ms=ONE_SECOND_MS,
        execution_session_id=testbed.context.execution_session_id,
    )
    assert session.action_id is not None

    # The testbed auto-approves commands; an outside cwd still asks.
    with pytest.raises(BrokerApprovalRequiredError) as asked:
        await _bash(testbed, cwd=outside, command=command)
    apply_approval_decision(
        db_path=testbed.db_path,
        busy_timeout_ms=ONE_SECOND_MS,
        tool_request_id="request-outside",
        user_id="user-1",
        action_id=session.action_id,
        approval_session_id=asked.value.approval_session_id,
        decision="approved_once",
        decided_at=INTEGRATION_APPROVAL_TIMESTAMP,
    )
    outcome = await _bash(testbed, cwd=outside, command=command)

    assert outcome.status == "success", outcome.output
    assert (outside / "made.txt").read_text() == "made\n"
    assert outcome.output["stdout"] == "denied\n"
    assert not sibling.exists()
