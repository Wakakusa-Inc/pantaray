from __future__ import annotations

import os
import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_resource_authority import (
    LegacyActionSharedTempPrecleanupAuthority,
    LegacyActionSharedTempResourceAuthority,
    list_legacy_action_shared_temp_precleanup_authorities_in_connection,
    list_legacy_action_shared_temp_resource_authorities_in_connection,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.tooling.locks.workspace_lock import (
    workspace_root_lock_path,
)
from pantaray_agents.local_runtime.tooling.resources.resource_tracking import (
    register_process_group_resource,
    register_workspace_lock_resource,
)

from .action_seed import insert_agent_action
from .legacy_action_shared_temp_test_support import (
    TIMESTAMP,
    seed_legacy_shared_temp_action,
)
from .resource_recovery_test_support import register_running_bash_invocation


def _seed(tmp_path: Path) -> tuple[Path, object, Path]:
    db_path, context, fixed_root = seed_legacy_shared_temp_action(tmp_path)
    register_running_bash_invocation(db_path=db_path, context=context)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE tool_runtime_resources SET resource_path=? "
            "WHERE action_id='action-1' AND tool_invocation_id IS NULL",
            (str(fixed_root),),
        )
        connection.execute(
            "UPDATE tool_invocations SET tool_request_id=NULL WHERE invocation_id='invocation-1'"
        )
    return db_path, context, fixed_root


def _load(db_path: Path) -> tuple[object, ...]:
    resolved = db_path.resolve()
    with sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_resource_authorities_in_connection(
            connection=connection, resolved_db_path=resolved
        )


def _load_precleanup(db_path: Path) -> tuple[object, ...]:
    resolved = db_path.resolve()
    with sqlite3.connect(f"{resolved.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_precleanup_authorities_in_connection(
            connection=connection, resolved_db_path=resolved
        )


def test_exact_producer_inventory_returns_strict_authority(tmp_path: Path) -> None:
    db_path, _, fixed_root = _seed(tmp_path)

    authority = _load(db_path)[0]

    assert isinstance(authority, LegacyActionSharedTempResourceAuthority)
    assert [row.invocation_id for row in authority.invocations] == ["invocation-1"]
    assert authority.invocations[0].tool_request_id is None
    assert [row.resource_path for row in authority.resources] == [str(fixed_root)]


def test_current_producer_cross_action_step_is_rejected(tmp_path: Path) -> None:
    db_path, context, _ = _seed(tmp_path)
    insert_agent_action(
        db_path=db_path, suggestion_id="suggestion-2", action_id="action-2"
    )
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            """INSERT INTO agent_action_steps(
                   step_id,action_id,user_id,step_number,local_step_number,short_step_id,
                   step_type,step_name,status,created_at)
               VALUES ('step-cross','action-2','user-1',1,1,'S-1-THINK',
                       'llm_output','thinking','success',?)""",
            (TIMESTAMP,),
        )
    register_running_bash_invocation(
        db_path=db_path, context=context, invocation_id="cross"
    )

    with pytest.raises(MigrationError, match="invocation authority"):
        _load(db_path)


def test_active_external_lock_returns_only_precleanup_authority(tmp_path: Path) -> None:
    db_path, context, _ = _seed(tmp_path)
    lock_path = workspace_root_lock_path(
        db_path=db_path.resolve(), lock_key="workspace"
    )
    resource_id = register_workspace_lock_resource(
        db_path=db_path,
        busy_timeout_ms=1_000,
        execution_session_id=context.execution_session_id,
        tool_invocation_id="invocation-1",
        action_id="action-1",
        lock_id="lock-1",
        lock_path=lock_path,
        created_at=TIMESTAMP,
    )

    authority = _load_precleanup(db_path)[0]

    assert isinstance(authority, LegacyActionSharedTempPrecleanupAuthority)
    assert [(row.resource_id, row.resource_path) for row in authority.resources] == [
        (resource_id, str(lock_path))
    ]
    with pytest.raises(MigrationError, match="require cleanup"):
        _load(db_path)


def test_active_process_group_returns_only_precleanup_authority(tmp_path: Path) -> None:
    db_path, context, _ = _seed(tmp_path)
    resource_id = register_process_group_resource(
        db_path=db_path,
        busy_timeout_ms=1_000,
        execution_session_id=context.execution_session_id,
        tool_invocation_id="invocation-1",
        action_id="action-1",
        pid=os.getpid(),
        created_at=TIMESTAMP,
    )

    authority = _load_precleanup(db_path)[0]

    assert isinstance(authority, LegacyActionSharedTempPrecleanupAuthority)
    assert [(row.resource_id, row.resource_kind) for row in authority.resources] == [
        (resource_id, "process_group")
    ]
    with pytest.raises(MigrationError, match="require cleanup"):
        _load(db_path)
