import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime import action_subagent_terminal as terminal
from pantaray_agents.local_runtime.runtime import job_payload_models
from pantaray_agents.local_runtime.runtime.action_subagent_cancel import (
    ActionSubagentCancelAuthorityError,
    ActionSubagentCancelRequest,
    request_action_subagent_cancellation,
)
from pantaray_agents.local_runtime.runtime.job_claim import claim_next_pending_job
from pantaray_agents.local_runtime.runtime.job_control import (
    requeue_claimed_local_job_after_dispatch_failure,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.tasks.types import ActionSubagentJobPayload

from . import test_action_subagent_spawn as spawn


def _child(tmp_path: Path, *, running: bool) -> tuple[Path, ActionSubagentJobPayload]:
    db_path, context = spawn._runtime(tmp_path)
    spawned = spawn._spawn(db_path, spawn._request(context))
    if running:
        claimed = claim_next_pending_job(
            db_path=str(db_path),
            busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
            job_type="execute_action_subagent",
            owner_user_id="user-1",
            claimed_by="test-worker",
            process_running_status="running",
            expected_process_pending_status="enqueued",
        )
        assert claimed is not None
    with spawn._connect(db_path) as connection:
        raw = connection.execute(
            "SELECT payload_json FROM job_payloads WHERE job_id=?", (spawned.job_id,)
        ).fetchone()[0]
    return db_path, job_payload_models.parse_action_subagent_job_payload_json(str(raw))


def _request_cancel(
    db_path: Path,
    payload: ActionSubagentJobPayload,
    *,
    parent_job_id: str = "parent-job",
) -> None:
    request_action_subagent_cancellation(
        db_path=db_path,
        busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
        request=ActionSubagentCancelRequest(
            user_id=payload["user_id"],
            action_id=payload["action_id"],
            parent_process_id=payload["parent_process_id"],
            parent_job_id=parent_job_id,
            child_process_id=payload["process_id"],
        ),
    )


def _snapshot(db_path: Path) -> tuple[object, ...]:
    with spawn._connect(db_path) as connection:
        return tuple(
            connection.execute(
                """SELECT job.status,process.status,(SELECT status FROM job_attempts WHERE job_id=job.job_id),claim.released_at IS NOT NULL,
                (SELECT COUNT(*) FROM process_events WHERE process_id=process.process_id) FROM jobs AS job JOIN processes AS process ON process.process_id=job.process_id
                JOIN action_subagent_resource_claims AS claim ON claim.child_process_id=process.process_id WHERE job.job_type='execute_action_subagent'"""
            ).fetchone()
        )


def _finalize(
    db_path: Path,
    payload: ActionSubagentJobPayload,
    result: terminal.ActionSubagentTerminalResult,
) -> terminal.ActionSubagentTerminalResult:
    return terminal.finalize_action_subagent_terminal(
        db_path=db_path,
        busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
        payload=payload,
        result=result,
    )


def test_running_terminal_releases_claim_and_replays_one_winner(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=True)
    result = terminal.build_action_subagent_success_result("report")
    assert _finalize(db_path, payload, result) == result
    assert _finalize(db_path, payload, result) == result
    assert _snapshot(db_path) == ("completed", "completed", "completed", 1, 1)


def test_claim_release_failure_rolls_back_terminal(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=True)
    result = terminal.build_action_subagent_success_result("report")
    with spawn._connect(db_path) as connection:
        connection.execute(
            "CREATE TRIGGER fail_release BEFORE UPDATE OF released_at "
            "ON action_subagent_resource_claims BEGIN "
            "SELECT RAISE(ABORT, 'forced release failure'); END"
        )
    with pytest.raises(sqlite3.IntegrityError, match="forced release failure"):
        _finalize(db_path, payload, result)
    assert _snapshot(db_path) == ("running", "running", "running", 0, 0)


def test_cancel_request_wins_late_success_and_failure(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=True)
    _request_cancel(db_path, payload)
    with spawn._connect(db_path) as connection:
        requested_at = connection.execute(
            "SELECT cancel_requested_at FROM jobs WHERE job_id=?",
            (payload["job_id"],),
        ).fetchone()[0]
    assert requested_at is not None
    assert _snapshot(db_path) == ("running", "running", "running", 0, 0)
    _request_cancel(db_path, payload)
    with spawn._connect(db_path) as connection:
        assert (
            connection.execute(
                "SELECT cancel_requested_at FROM jobs WHERE job_id=?",
                (payload["job_id"],),
            ).fetchone()[0]
            == requested_at
        )
    canceled = terminal.build_action_subagent_canceled_result()
    success = terminal.build_action_subagent_success_result("late")
    failure = terminal.build_action_subagent_failure_result("LATE_FAILURE")
    assert _finalize(db_path, payload, success) == canceled
    assert _finalize(db_path, payload, failure) == canceled
    _request_cancel(db_path, payload)
    assert _snapshot(db_path) == ("canceled", "canceled", "canceled", 1, 1)


def test_cancel_requires_active_exact_parent(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=False)
    with pytest.raises(ActionSubagentCancelAuthorityError, match="active parent"):
        _request_cancel(db_path, payload, parent_job_id="other-parent-job")
    assert _snapshot(db_path) == ("queued", "enqueued", None, 0, 0)


def test_queued_cancel_wins_claim_and_replays_terminal(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=False)
    _request_cancel(db_path, payload)
    assert _snapshot(db_path) == ("canceled", "canceled", None, 1, 1)
    assert (
        claim_next_pending_job(
            db_path=str(db_path),
            busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
            job_type="execute_action_subagent",
            owner_user_id="user-1",
            claimed_by="late-worker",
            process_running_status="running",
            expected_process_pending_status="enqueued",
        )
        is None
    )
    _request_cancel(db_path, payload)
    assert _snapshot(db_path) == ("canceled", "canceled", None, 1, 1)


def test_queued_cancel_reuses_connection_terminal_producer(tmp_path: Path) -> None:
    db_path, payload = _child(tmp_path, running=True)
    requeue_claimed_local_job_after_dispatch_failure(
        db_path=str(db_path),
        busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
        job_id=payload["job_id"],
        process_id=payload["process_id"],
        process_pending_status="enqueued",
    )
    canceled = terminal.build_action_subagent_canceled_result()
    with spawn._connect(db_path) as connection, immediate_transaction(connection):
        connection.execute(
            "UPDATE jobs SET cancel_requested_at=? WHERE job_id=?",
            (spawn.TIMESTAMP, payload["job_id"]),
        )
        result = terminal.finalize_action_subagent_terminal_in_connection(
            connection=connection,
            payload=payload,
            result=canceled,
            completed_at=spawn.TIMESTAMP,
        )
    assert result == {"outcome": "canceled"}
    assert _finalize(db_path, payload, canceled) == canceled
    assert _snapshot(db_path) == ("canceled", "canceled", "failed", 1, 1)
