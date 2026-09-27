from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.action_subagent_resource_authority import (
    ActionSubagentResourceActorError,
    ActionSubagentResourceWriteDeniedError,
    resolve_action_subagent_command_write_roots,
)
from pantaray_agents.local_runtime.tooling.action_subagent_resource_claims import (
    ActionSubagentResourceClaimConflictError,
)
from pantaray_agents.local_runtime.tooling.models import (
    ActionExecutionContext,
    CommandToolInvocationStartInput,
    ToolRuntimeResourceCreateInput,
)
from pantaray_agents.local_runtime.tooling.repository import (
    record_tool_invocation_start,
)
from pantaray_agents.local_runtime.tooling.resources.resource_repository import (
    create_tool_runtime_resource,
)

from .test_action_subagent_resource_claims import (
    ACQUIRED_AT,
    _acquire,
    _authorize,
    _connect,
    _runtime,
    _workspace_claim,
    _workspace_resource,
)


def _start_command(
    db_path: Path,
    context: ActionExecutionContext,
    *,
    actor: str = "parent-1",
    invocation_id: str = "command-1",
    roots: tuple[Path, ...] | None = None,
) -> None:
    record_tool_invocation_start(
        db_path=db_path,
        busy_timeout_ms=1_000,
        invocation=CommandToolInvocationStartInput(
            invocation_id=invocation_id,
            tool_request_id=f"request:{invocation_id}",
            user_id="user-1",
            action_id="action-1",
            step_id=f"step:{invocation_id}",
            tool_id="bash",
            manifest_id=context.manifest_id,
            execution_session_id=context.execution_session_id,
            cwd=str(context.workspace_path),
            timeout_ms=5_000,
            intent_class="process_exec_local",
            network_policy=context.network_policy,
            command_summary_json=None,
            capability_snapshot_json=None,
            request_json={"command": "pwd"},
            status="running",
            started_at=ACQUIRED_AT,
            actor_process_id=actor,
            write_roots=(context.workspace_path.resolve(),) if roots is None else roots,
        ),
    )


def test_start_rechecks_claims_and_active_actor_before_recording_grants(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )
    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _start_command(db_path, context)
    with _connect(db_path) as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM tool_invocations").fetchone()[0]
            == 0
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM command_workspace_write_grants"
            ).fetchone()[0]
            == 0
        )
    _start_command(db_path, context, roots=())
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE processes SET status = 'completed' WHERE process_id = 'parent-1'"
        )
    with pytest.raises(ActionSubagentResourceActorError):
        _start_command(db_path, context, invocation_id="inactive", roots=())


@pytest.mark.parametrize(
    "resource_status", [None, "active", "cleanup_failed", "abandoned"]
)
def test_claim_waits_for_invocation_and_process_cleanup(
    tmp_path: Path,
    resource_status: str | None,
) -> None:
    db_path, context = _runtime(tmp_path)
    _start_command(db_path, context)
    # Concurrent commands by the same actor retain the existing execution contract.
    _start_command(db_path, context, invocation_id="command-2")
    if resource_status is not None:
        create_tool_runtime_resource(
            db_path=db_path,
            busy_timeout_ms=1_000,
            resource=ToolRuntimeResourceCreateInput(
                resource_id="process-resource",
                execution_session_id=context.execution_session_id,
                tool_invocation_id="command-1",
                action_id="action-1",
                resource_kind="process_group",
                status=resource_status,
                created_at=ACQUIRED_AT,
                pid=12345,
                pgid=12345,
                process_start_signature="unreclaimed",
                resource_path=None,
            ),
        )
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE tool_invocations SET status = 'completed' WHERE invocation_id = 'command-2'"
        )
        if resource_status is not None:
            connection.execute(
                "UPDATE tool_invocations SET status = 'failed' WHERE invocation_id = 'command-1'"
            )
        connection.commit()
        with pytest.raises(ActionSubagentResourceClaimConflictError):
            _acquire(
                connection,
                child_process_id="child-1",
                claims=(_workspace_claim(context, "claim-1", "claimed"),),
            )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM action_subagent_resource_claims"
            ).fetchone()[0]
            == 0
        )
        connection.execute("UPDATE tool_invocations SET status = 'completed'")
        connection.execute(
            "UPDATE tool_runtime_resources SET status = 'cleaned' WHERE resource_id = 'process-resource'"
        )
        connection.commit()
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM action_subagent_resource_claims"
            ).fetchone()[0]
            == 1
        )


def test_released_child_claim_does_not_release_live_command_authority(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )
    _start_command(
        db_path,
        context,
        actor="child-1",
        roots=((context.workspace_path / "claimed").resolve(),),
    )
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE action_subagent_resource_claims SET released_at = ?", (ACQUIRED_AT,)
        )
    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _authorize(
            db_path,
            actor_process_id="parent-1",
            resources=(_workspace_resource(context, "claimed/file"),),
        )
    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _start_command(db_path, context, invocation_id="parent-command")
    assert (
        resolve_action_subagent_command_write_roots(
            db_path=db_path,
            busy_timeout_ms=1_000,
            user_id="user-1",
            action_id="action-1",
            actor_process_id="parent-1",
            candidate_roots=(_workspace_resource(context, "."),),
        )
        == ()
    )
    with _connect(db_path) as connection:
        with pytest.raises(ActionSubagentResourceClaimConflictError):
            _acquire(
                connection,
                child_process_id="child-2",
                claims=(_workspace_claim(context, "claim-2", "claimed"),),
            )
    _authorize(
        db_path,
        actor_process_id="parent-1",
        resources=(_workspace_resource(context, "elsewhere/file"),),
    )
