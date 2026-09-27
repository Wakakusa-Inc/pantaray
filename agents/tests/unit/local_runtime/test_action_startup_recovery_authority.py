from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import cast

import pytest

from pantaray_agents.agents.action_agent.runtime.checkpoint import (
    RUNTIME_STATE_CHECKPOINT_VERSION,
)
from pantaray_agents.local_runtime.runtime.action_message_process_fence import (
    ActionLogicalRunLineage,
)
from pantaray_agents.local_runtime.runtime.action_startup_recovery_authority import (
    load_action_startup_recovery_authority_in_connection,
)
from pantaray_agents.local_runtime.runtime.action_startup_recovery_envelope import (
    ActionStartupRecoveryActionStatus,
    ActionStartupRecoveryAnchor,
    ActionStartupRecoveryEnvelope,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError
from pantaray_agents.local_runtime.tooling.models import ActionExecutionContext
from pantaray_agents.local_runtime.tooling.resources.resource_db_support import (
    configure_connection,
)

from .resource_recovery_test_support import bootstrap_runtime_db

TIMESTAMP = "2026-08-29T00:00:00Z"
SESSION_STARTED_AT = "2026-03-23T00:00:00Z"
SESSION_COMPLETED_AT = "2026-03-24T00:00:00Z"


def _envelope(
    *,
    action_status: ActionStartupRecoveryActionStatus = "processing",
    attempt_started_at: str = SESSION_STARTED_AT,
    approval: bool = False,
) -> ActionStartupRecoveryEnvelope:
    continuation_ref: dict[str, str] = (
        {
            "kind": "tool_approval",
            "approval_session_id": "approval-1",
            "tool_request_id": "request-1",
        }
        if approval
        else {"kind": "user_step", "user_step_id": "anchor-2"}
    )
    return ActionStartupRecoveryEnvelope(
        job_id="job-1",
        process_id="process-1",
        user_id="user-1",
        action_id="action-1",
        action_status=action_status,
        attempt=1,
        attempt_id="attempt-1",
        attempt_started_at=attempt_started_at,
        claimed_by="worker-1",
        claimed_at=TIMESTAMP,
        job_heartbeat_at=TIMESTAMP,
        process_updated_at=TIMESTAMP,
        process_heartbeat_at=TIMESTAMP,
        payload_json=json.dumps(
            {
                "job_id": "job-1",
                "process_id": "process-1",
                "action_id": "action-1",
                "user_id": "user-1",
                "continuation_ref": continuation_ref,
            }
        ),
        lineage=ActionLogicalRunLineage(
            root_process_id="process-1",
            root_accepted_sequence=1,
            job_id="job-1",
        ),
        anchor=ActionStartupRecoveryAnchor(step_id="anchor-2", step_number=2),
    )


def _context(context: ActionExecutionContext) -> dict[str, object]:
    return {
        "manifest_id": context.manifest_id,
        "execution_session_id": context.execution_session_id,
        "execution_network_policy": context.network_policy,
        "action_temp_dir": str(context.action_temp_dir),
        "app_runtime_python": str(context.app_runtime_python),
        "read_access_scope": context.read_access_scope,
    }


def _insert_checkpoint(
    connection: sqlite3.Connection,
    *,
    step_id: str,
    step_number: int,
    checkpoint: dict[str, object],
    version: int = RUNTIME_STATE_CHECKPOINT_VERSION,
) -> None:
    connection.execute(
        """INSERT INTO agent_action_steps(
            step_id,action_id,user_id,step_number,local_step_number,short_step_id,
            step_type,step_name,status,runtime_state_checkpoint,
            runtime_state_checkpoint_version,created_at
        ) VALUES (?, 'action-1','user-1',?,?,?,'llm_output','thinking',
                  'success',?,?,?)""",
        (
            step_id,
            step_number,
            step_number,
            f"S-{step_number}-THINK",
            json.dumps(checkpoint),
            version,
            TIMESTAMP,
        ),
    )


def _bootstrap(tmp_path: Path) -> tuple[Path, ActionExecutionContext]:
    db_path, raw_context = bootstrap_runtime_db(tmp_path)
    context = cast(ActionExecutionContext, raw_context)
    with sqlite3.connect(db_path) as connection:
        _insert_checkpoint(
            connection,
            step_id="old-run-checkpoint",
            step_number=1,
            checkpoint={},
        )
    return db_path, context


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    configure_connection(connection, 1_000)
    connection.execute("BEGIN")
    return connection


@pytest.mark.parametrize(
    ("checkpoint_kind", "session_status"),
    [
        ("none", "running"),
        ("contextless", "running"),
        ("bound", "expired"),
        ("none", "completed"),
        ("none", "failed"),
    ],
)
def test_authority_binds_current_session_from_checkpoint_or_producer_time(
    tmp_path: Path, checkpoint_kind: str, session_status: str
) -> None:
    db_path, context = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        if checkpoint_kind != "none":
            _insert_checkpoint(
                connection,
                step_id="current-run-checkpoint",
                step_number=2,
                checkpoint=_context(context) if checkpoint_kind == "bound" else {},
            )
        if session_status != "running":
            connection.execute(
                "UPDATE execution_sessions SET status='expired',completed_at=?",
                (SESSION_COMPLETED_AT,),
            )
            connection.execute(
                "UPDATE execution_sessions SET status=?", (session_status,)
            )
    with _connect(db_path) as connection:
        authority = load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(),
        )
        queued = load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(action_status="queued"),
        )
    assert authority is not None
    assert queued is None
    assert authority.session_status == session_status
    assert authority.checkpoint.step_id == (
        "current-run-checkpoint" if checkpoint_kind != "none" else None
    )


def test_authority_ignores_stale_terminal_manifest_from_prior_turn(
    tmp_path: Path,
) -> None:
    db_path, _ = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE execution_sessions SET status='completed',completed_at=?",
            (SESSION_COMPLETED_AT,),
        )
        connection.execute(
            "UPDATE tool_runtime_resources SET status='cleaned',cleaned_at=?,updated_at=? "
            "WHERE action_id='action-1'",
            (SESSION_COMPLETED_AT, SESSION_COMPLETED_AT),
        )
    with _connect(db_path) as connection:
        authority = load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(attempt_started_at=TIMESTAMP),
        )
    assert authority is None


def test_authority_rejects_terminal_timestamp_inversion(tmp_path: Path) -> None:
    db_path, _ = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE execution_sessions SET status='completed',started_at=?,completed_at=?",
            ("2026-03-25T00:00:00Z", SESSION_COMPLETED_AT),
        )
    with (
        _connect(db_path) as connection,
        pytest.raises(MigrationError, match="completion precedes"),
    ):
        load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(),
        )


def test_authority_retains_exact_pending_approval(tmp_path: Path) -> None:
    db_path, context = _bootstrap(tmp_path)
    checkpoint = _context(context)
    checkpoint["pending_approval_request"] = {
        "approval_session_id": "approval-1",
        "tool_request_id": "request-1",
    }
    with sqlite3.connect(db_path) as connection, connection:
        _insert_checkpoint(
            connection,
            step_id="pending-checkpoint",
            step_number=2,
            checkpoint=checkpoint,
        )
        connection.execute(
            """INSERT INTO approval_sessions(
                approval_session_id,user_id,action_id,manifest_id,tool_request_id,
                tool_id,intent_class,approval_source,status,approved_capabilities_json,
                command_summary_json,requested_at,created_at
            ) VALUES ('approval-1','user-1','action-1',?,'request-1','read',
                      'read_only','prompt','pending','[]','{}',?,?)""",
            (context.manifest_id, TIMESTAMP, TIMESTAMP),
        )
    with _connect(db_path) as connection:
        authority = load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(attempt_started_at=TIMESTAMP, approval=True),
        )
    assert authority is not None
    assert authority.pending_approval_outcome == "retain"

    with sqlite3.connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE agent_action_steps SET runtime_state_checkpoint='{}' "
            "WHERE step_id='pending-checkpoint'"
        )
    with (
        _connect(db_path) as connection,
        pytest.raises(
            MigrationError, match="pending approval has no bound current-run checkpoint"
        ),
    ):
        load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(),
        )


def test_authority_rejects_noncurrent_checkpoint_version(tmp_path: Path) -> None:
    db_path, context = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        _insert_checkpoint(
            connection,
            step_id="old-version-checkpoint",
            step_number=2,
            checkpoint=_context(context),
            version=RUNTIME_STATE_CHECKPOINT_VERSION - 1,
        )
    with (
        _connect(db_path) as connection,
        pytest.raises(MigrationError, match="checkpoint version is not current"),
    ):
        load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(),
        )


@pytest.mark.parametrize("corruption", ["resource", "checkpoint", "owner", "workspace"])
def test_authority_rejects_partial_or_mismatched_resource_authority(
    tmp_path: Path, corruption: str
) -> None:
    db_path, context = _bootstrap(tmp_path)
    with sqlite3.connect(db_path) as connection, connection:
        if corruption == "resource":
            connection.execute(
                "UPDATE tool_runtime_resources SET resource_path='/wrong' "
                "WHERE action_id='action-1'"
            )
        elif corruption == "checkpoint":
            checkpoint = _context(context)
            checkpoint["execution_session_id"] = "session-other"
            _insert_checkpoint(
                connection,
                step_id="mismatched-checkpoint",
                step_number=2,
                checkpoint=checkpoint,
            )
        elif corruption == "owner":
            connection.execute(
                "INSERT INTO users(user_id,ui_language,created_at,updated_at) "
                "VALUES ('user-2','ja',?,?)",
                (TIMESTAMP, TIMESTAMP),
            )
            connection.execute("UPDATE workspace_manifests SET user_id='user-2'")
        else:
            connection.execute(
                "UPDATE workspace_manifests SET scratch_root_path='/outside'"
            )
            connection.execute("UPDATE execution_sessions SET cwd_path='/outside'")
    with _connect(db_path) as connection, pytest.raises(MigrationError):
        load_action_startup_recovery_authority_in_connection(
            connection=connection,
            db_path=db_path,
            envelope=_envelope(),
        )
