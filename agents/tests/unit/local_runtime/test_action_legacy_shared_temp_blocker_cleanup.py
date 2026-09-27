from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from unittest.mock import Mock

import pytest

from pantaray_agents.local_runtime.runtime import (
    action_legacy_shared_temp_blocker_cleanup as cleanup_module,
)
from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_blocker_cleanup import (
    reconcile_legacy_action_shared_temp_blockers,
)
from pantaray_agents.local_runtime.runtime.action_legacy_shared_temp_resource_authority import (
    LegacyActionSharedTempPrecleanupAuthority,
    list_legacy_action_shared_temp_precleanup_authorities_in_connection,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.tooling.locks.workspace_lock_coordinator import (
    WorkspaceLockLease,
    acquire_workspace_root_lock,
)
from pantaray_agents.local_runtime.tooling.resources.resource_store import (
    load_tool_runtime_resource,
)
from pantaray_agents.local_runtime.tooling.resources.resource_tracking import (
    register_process_group_resource,
)

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
    fixed_root.mkdir(parents=True, exist_ok=True)
    (fixed_root / "sentinel").write_text("keep", encoding="utf-8")
    return db_path.resolve(), context, fixed_root


def _authority(db_path: Path) -> tuple[LegacyActionSharedTempPrecleanupAuthority, ...]:
    with sqlite3.connect(f"{db_path.as_uri()}?mode=ro", uri=True) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA query_only=ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_precleanup_authorities_in_connection(
            connection=connection, resolved_db_path=db_path
        )


def _process(db_path: Path, context: object, *, pid: int) -> str:
    resource_id = register_process_group_resource(
        db_path=db_path,
        busy_timeout_ms=1_000,
        execution_session_id=context.execution_session_id,
        tool_invocation_id="invocation-1",
        action_id="action-1",
        pid=pid,
        created_at=TIMESTAMP,
    )
    assert resource_id is not None
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE tool_runtime_resources SET pgid=NULL,process_start_signature=NULL "
            "WHERE resource_id=?",
            (resource_id,),
        )
    return resource_id


def _lock(db_path: Path, context: object) -> WorkspaceLockLease:
    return acquire_workspace_root_lock(
        db_path=db_path,
        busy_timeout_ms=1_000,
        lock_key=str(context.workspace_path),
        workspace_root=context.workspace_path,
        execution_session_id=context.execution_session_id,
        tool_invocation_id="invocation-1",
        action_id="action-1",
        acquired_at=TIMESTAMP,
    )


def _reconcile(db_path: Path) -> None:
    reconcile_legacy_action_shared_temp_blockers(
        resolved_db_path=db_path,
        busy_timeout_ms=1_000,
        authorities=_authority(db_path),
    )


def _status(db_path: Path, resource_id: str) -> tuple[str, int]:
    resource = load_tool_runtime_resource(
        db_path=db_path, busy_timeout_ms=1_000, resource_id=resource_id
    )
    return resource.status, resource.cleanup_attempts


def test_process_and_lock_cleanup_preserves_fixed_root(tmp_path: Path) -> None:
    db_path, context, fixed_root = _seed(tmp_path)
    process_id = _process(db_path, context, pid=2_147_483_647)
    lock = _lock(db_path, context)

    _reconcile(db_path)

    assert not lock.lock_path.exists()
    assert (fixed_root / "sentinel").read_text(encoding="utf-8") == "keep"
    with sqlite3.connect(db_path) as connection:
        rows = connection.execute(
            "SELECT resource.resource_id,resource.status,event.event_type "
            "FROM tool_runtime_resources AS resource JOIN tool_runtime_resource_events AS event "
            "ON event.resource_id=resource.resource_id "
            "WHERE resource.resource_id IN (?,?) ORDER BY resource.resource_id",
            (process_id, lock.resource_id),
        ).fetchall()
    assert rows == sorted(
        [
            (process_id, "cleaned", "legacy_action_external_resource_cleaned"),
            (lock.resource_id, "cleaned", "legacy_action_external_resource_cleaned"),
        ]
    )


def test_process_failure_exhausts_retries_before_lock_cleanup(tmp_path: Path) -> None:
    db_path, context, fixed_root = _seed(tmp_path)
    process_id = _process(db_path, context, pid=os.getpid())
    lock = _lock(db_path, context)

    for _ in range(3):
        with pytest.raises(MigrationError, match="process-group blocker"):
            _reconcile(db_path)
        assert lock.lock_path.exists()
        assert (fixed_root / "sentinel").exists()

    assert _status(db_path, process_id) == ("abandoned", 3)
    with pytest.raises(MigrationError, match="process-group cleanup is not retryable"):
        _authority(db_path)


def test_physical_cleanup_before_transition_converges_on_restart(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db_path, context, fixed_root = _seed(tmp_path)
    lock = _lock(db_path, context)
    transition = cleanup_module.persist_tool_runtime_resource_transition
    monkeypatch.setattr(
        cleanup_module,
        "persist_tool_runtime_resource_transition",
        Mock(side_effect=sqlite3.OperationalError("interrupted")),
    )

    with pytest.raises(sqlite3.OperationalError, match="interrupted"):
        _reconcile(db_path)
    assert not lock.lock_path.exists()
    assert _status(db_path, lock.resource_id)[0] == "active"

    monkeypatch.setattr(
        cleanup_module, "persist_tool_runtime_resource_transition", transition
    )
    _reconcile(db_path)
    assert _status(db_path, lock.resource_id)[0] == "cleaned"
    assert (fixed_root / "sentinel").read_text(encoding="utf-8") == "keep"
