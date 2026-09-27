from __future__ import annotations

import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier
from typing import cast

import pytest
from pydantic import ValidationError

from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.tooling.models import (
    ExecutionSessionCreateInput,
    ExecutionSessionTerminalStatus,
)
from pantaray_agents.local_runtime.tooling.repository.executions import (
    ExecutionSessionCompletionStatusError,
    ExecutionSessionNotFoundError,
    ExecutionSessionParentConflictError,
    ExecutionSessionTerminalStateError,
    complete_execution_session,
    create_execution_session,
    load_action_job_root_execution_session_id,
)
from pantaray_agents.local_runtime.tooling.resources.resource_repository import (
    list_recoverable_tool_runtime_resources_for_action,
)

from .action_seed import insert_agent_action
from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000
STARTED_AT = "2026-08-28T00:00:00Z"


def _setup_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    insert_agent_action(db_path=db_path)
    insert_agent_action(
        db_path=db_path,
        suggestion_id="suggestion-2",
        action_id="action-2",
    )
    insert_agent_action(
        db_path=db_path,
        user_id="user-2",
        suggestion_id="suggestion-3",
        action_id="action-3",
    )
    return db_path


def _session_input(
    *,
    session_id: str,
    user_id: str = "user-1",
    action_id: str | None = "action-1",
    parent_id: str | None = None,
) -> ExecutionSessionCreateInput:
    return ExecutionSessionCreateInput(
        execution_session_id=session_id,
        user_id=user_id,
        action_id=action_id,
        parent_execution_session_id=parent_id,
        exec_mode="brokered_file_ops",
        cwd_path="/workspace",
        action_temp_dir=f"/runtime-temp/{session_id}",
        app_runtime_python="/app/python",
        network_policy="cloud-proxy-only",
        read_access_scope="workspace",
        capability_snapshot_json={},
        tool_allowlist_json=[],
        status="running",
        started_at=STARTED_AT,
        expires_at=None,
    )


def _create(
    db_path: Path,
    *,
    session_id: str,
    user_id: str = "user-1",
    action_id: str | None = "action-1",
    parent_id: str | None = None,
) -> None:
    create_execution_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        session=_session_input(
            session_id=session_id,
            user_id=user_id,
            action_id=action_id,
            parent_id=parent_id,
        ),
    )


def _session_rows(db_path: Path) -> list[tuple[object, ...]]:
    with sqlite3.connect(db_path) as connection:
        return connection.execute(
            """
            SELECT execution_session_id, parent_execution_session_id,
                   user_id, action_id, status, completed_at
            FROM execution_sessions
            ORDER BY execution_session_id
            """
        ).fetchall()


@pytest.mark.parametrize("status", ["completed", "failed", "canceled", "expired"])
def test_execution_session_create_input_accepts_only_running(status: str) -> None:
    payload = _session_input(session_id="session-1").model_dump()
    payload["status"] = status

    with pytest.raises(ValidationError):
        ExecutionSessionCreateInput.model_validate(payload)


def test_root_and_exact_bound_child_sessions_are_created(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="parent")
    _create(db_path, session_id="child", parent_id="parent")

    assert _session_rows(db_path) == [
        ("child", "parent", "user-1", "action-1", "running", None),
        ("parent", None, "user-1", "action-1", "running", None),
    ]


def test_terminal_action_rejects_late_root_session(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE agent_actions SET status = 'canceled', updated_at = ? "
            "WHERE action_id = 'action-1'",
            (STARTED_AT,),
        )
        connection.commit()

    with pytest.raises(ExecutionSessionParentConflictError):
        _create(db_path, session_id="late-root")

    assert _session_rows(db_path) == []


def test_terminal_cleanup_identity_exactly_binds_running_job_and_excludes_root(
    tmp_path: Path,
) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="session-1")
    complete_execution_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        execution_session_id="session-1",
        status="failed",
        completed_at=STARTED_AT,
    )
    with sqlite3.connect(db_path) as connection:
        connection.executescript(
            f"""
            INSERT INTO workspace_manifests(
                manifest_id, user_id, action_id, execution_session_id,
                scratch_root_path, created_at, materialized_at, status
            ) VALUES (
                'manifest-1', 'user-1', 'action-1', 'session-1',
                '/scratch', '{STARTED_AT}', '{STARTED_AT}', 'ready'
            );
            INSERT INTO processes(
                process_id, user_id, kind, status, suggestion_id, action_id,
                started_at, updated_at, heartbeat_at, current_job_id, next_event_seq
            ) VALUES (
                'process-1', 'user-1', 'action', 'running', 'suggestion-1',
                'action-1', '{STARTED_AT}', '{STARTED_AT}', '{STARTED_AT}',
                'job-1', 1
            );
            INSERT INTO jobs(
                job_id, user_id, job_type, process_id, status, attempt,
                scheduled_at, started_at, heartbeat_at, logical_key
            ) VALUES (
                'job-1', 'user-1', 'execute_action', 'process-1', 'running', 1,
                '{STARTED_AT}', '{STARTED_AT}', '{STARTED_AT}', 'action-1'
            );
            UPDATE agent_actions SET status = 'error', updated_at = '{STARTED_AT}'
            WHERE action_id = 'action-1';
            INSERT INTO tool_runtime_resources(
                resource_id, execution_session_id, tool_invocation_id, action_id,
                resource_kind, status, resource_path, created_at, updated_at,
                cleanup_attempts
            ) VALUES
                ('root', 'session-1', NULL, 'action-1', 'temp_dir', 'active',
                 '/session-1', '{STARTED_AT}', '{STARTED_AT}', 0),
                ('child', 'session-1', NULL, 'action-1', 'temp_file', 'active',
                 '/session-1/child', '{STARTED_AT}', '{STARTED_AT}', 0);
            """
        )

    assert (
        load_action_job_root_execution_session_id(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            job_id="job-1",
            process_id="process-1",
            user_id="user-1",
            action_id="action-1",
        )
        == "session-1"
    )
    resources = list_recoverable_tool_runtime_resources_for_action(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        action_id="action-1",
        execution_session_id="session-1",
    )
    assert [resource.resource_id for resource in resources] == ["child"]

    with sqlite3.connect(db_path) as connection:
        connection.execute(
            "UPDATE processes SET current_job_id = NULL WHERE process_id = 'process-1'"
        )
        connection.commit()
    assert (
        load_action_job_root_execution_session_id(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            job_id="job-1",
            process_id="process-1",
            user_id="user-1",
            action_id="action-1",
        )
        is None
    )


def test_null_action_child_exactly_binds_to_null_action_parent(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="parent", action_id=None)
    _create(db_path, session_id="child", action_id=None, parent_id="parent")

    assert _session_rows(db_path) == [
        ("child", "parent", "user-1", None, "running", None),
        ("parent", None, "user-1", None, "running", None),
    ]


@pytest.mark.parametrize("status", ["completed", "failed", "canceled", "expired"])
def test_terminal_parent_rejects_new_child(tmp_path: Path, status: str) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="parent")
    complete_execution_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        execution_session_id="parent",
        status=cast(ExecutionSessionTerminalStatus, status),
        completed_at="2026-08-28T00:00:01Z",
    )

    with pytest.raises(ExecutionSessionParentConflictError):
        _create(db_path, session_id="child", parent_id="parent")

    assert [row[0] for row in _session_rows(db_path)] == ["parent"]


def test_child_creation_and_parent_completion_serialize_atomically(
    tmp_path: Path,
) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="parent")
    start = Barrier(2)

    def create_child() -> bool:
        start.wait()
        try:
            _create(db_path, session_id="child", parent_id="parent")
        except ExecutionSessionParentConflictError:
            return False
        return True

    def complete_parent() -> None:
        start.wait()
        complete_execution_session(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            execution_session_id="parent",
            status="completed",
            completed_at="2026-08-28T00:00:01Z",
        )

    with ThreadPoolExecutor(max_workers=2) as executor:
        child_future = executor.submit(create_child)
        completion_future = executor.submit(complete_parent)
        child_created = child_future.result()
        completion_future.result()

    expected_rows: list[tuple[object, ...]] = (
        [("child", "parent", "user-1", "action-1", "running", None)]
        if child_created
        else []
    )
    expected_rows.append(
        (
            "parent",
            None,
            "user-1",
            "action-1",
            "completed",
            "2026-08-28T00:00:01Z",
        )
    )
    assert _session_rows(db_path) == expected_rows


@pytest.mark.parametrize(
    ("user_id", "action_id"),
    [("user-1", "action-2"), ("user-2", "action-3")],
)
def test_child_rejects_cross_owner_parent(
    tmp_path: Path,
    user_id: str,
    action_id: str,
) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="parent")

    with pytest.raises(ExecutionSessionParentConflictError):
        _create(
            db_path,
            session_id="child",
            user_id=user_id,
            action_id=action_id,
            parent_id="parent",
        )

    assert [row[0] for row in _session_rows(db_path)] == ["parent"]


def test_child_rejects_missing_parent_without_durable_side_effect(
    tmp_path: Path,
) -> None:
    db_path = _setup_db(tmp_path)

    with pytest.raises(ExecutionSessionParentConflictError):
        _create(db_path, session_id="child", parent_id="missing")

    assert _session_rows(db_path) == []


@pytest.mark.parametrize("status", ["completed", "failed", "canceled", "expired"])
def test_running_session_completes_once(tmp_path: Path, status: str) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="session-1")

    complete_execution_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        execution_session_id="session-1",
        status=cast(ExecutionSessionTerminalStatus, status),
        completed_at="2026-08-28T00:00:01Z",
    )

    assert _session_rows(db_path) == [
        (
            "session-1",
            None,
            "user-1",
            "action-1",
            status,
            "2026-08-28T00:00:01Z",
        )
    ]


@pytest.mark.parametrize("next_status", ["completed", "failed", "canceled"])
def test_terminal_session_is_immutable(tmp_path: Path, next_status: str) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="session-1")
    complete_execution_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        execution_session_id="session-1",
        status="completed",
        completed_at="2026-08-28T00:00:01Z",
    )

    with pytest.raises(ExecutionSessionTerminalStateError) as error:
        complete_execution_session(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            execution_session_id="session-1",
            status=cast(ExecutionSessionTerminalStatus, next_status),
            completed_at="2026-08-28T00:00:02Z",
        )

    assert error.value.current_status == "completed"
    assert error.value.requested_status == next_status
    assert _session_rows(db_path)[0][4:] == (
        "completed",
        "2026-08-28T00:00:01Z",
    )


def test_completion_rejects_non_terminal_status(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)
    _create(db_path, session_id="session-1")

    with pytest.raises(
        ExecutionSessionCompletionStatusError, match="requires a terminal status"
    ):
        complete_execution_session(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            execution_session_id="session-1",
            status=cast(ExecutionSessionTerminalStatus, "running"),
            completed_at="2026-08-28T00:00:01Z",
        )

    assert _session_rows(db_path)[0][4:] == ("running", None)


def test_completion_distinguishes_missing_session(tmp_path: Path) -> None:
    db_path = _setup_db(tmp_path)

    with pytest.raises(ExecutionSessionNotFoundError):
        complete_execution_session(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            execution_session_id="missing",
            status="failed",
            completed_at="2026-08-28T00:00:01Z",
        )
