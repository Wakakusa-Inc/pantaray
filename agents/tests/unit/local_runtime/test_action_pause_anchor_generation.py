"""The relay releases only on the pause anchor the root currently rests on.

The relay stubs this predicate in its own tests, so the SQL that decides whether
a pause anchor is still the live one is exercised here against a real database
across every generation the root walks through.
"""

from __future__ import annotations

from pathlib import Path

from pantaray_agents.local_runtime.runtime.process_events import (
    mark_local_action_job_paused,
)
from pantaray_agents.orchestration.ws.action_relay_forwarder_local import (
    _pause_anchor_still_holds,
)

from . import test_action_subagent_spawn as spawn

ROOT_PROCESS_ID = "parent-process"
ROOT_JOB_ID = "parent-job"


def _insert_pending_session(db_path: Path, *, session_id: str, request_id: str) -> None:
    with spawn._connect(db_path) as connection, connection:
        connection.execute(
            "INSERT INTO approval_sessions(approval_session_id,user_id,action_id,"
            "tool_request_id,tool_id,intent_class,approval_source,status,"
            "approved_capabilities_json,command_summary_json,requested_at,created_at)"
            " VALUES (?,'user-1','action-1',?,'apply_patch','write','prompt',"
            "'pending','{}','{}',?,?)",
            (session_id, request_id, spawn.TIMESTAMP, spawn.TIMESTAMP),
        )


def _latest_anchor_cursor(db_path: Path) -> int:
    with spawn._connect(db_path) as connection:
        row = connection.execute(
            "SELECT MAX(process_event_rowid) FROM process_events "
            "WHERE process_id=? AND event_name='process_paused'",
            (ROOT_PROCESS_ID,),
        ).fetchone()
    return int(row[0])


def _pause_root(db_path: Path, *, session_id: str, request_id: str) -> int:
    """Park the running root on a new approval anchor and return its cursor."""

    _insert_pending_session(db_path, session_id=session_id, request_id=request_id)
    with spawn._connect(db_path) as connection, connection:
        connection.execute("DELETE FROM job_attempts WHERE job_id=?", (ROOT_JOB_ID,))
        connection.execute(
            "INSERT INTO job_attempts(attempt_id,job_id,attempt_number,started_at,"
            "status) VALUES (?,?,1,?,'running')",
            (f"attempt-{session_id}", ROOT_JOB_ID, spawn.TIMESTAMP),
        )
    mark_local_action_job_paused(
        db_path=db_path,
        busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
        job_id=ROOT_JOB_ID,
        process_id=ROOT_PROCESS_ID,
        payload={
            "action_id": "action-1",
            "user_id": "user-1",
            "status": "processing",
            "completed_at": spawn.TIMESTAMP,
            "reason": "approval_pending",
            "approval_blockers": [
                {"approval_session_id": session_id, "tool_request_id": request_id}
            ],
        },
    )
    return _latest_anchor_cursor(db_path)


def _resume_root(db_path: Path) -> None:
    """Apply the approved decision's effect on the state this predicate reads."""

    with spawn._connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE processes SET status='enqueued',current_job_id=NULL "
            "WHERE process_id=?",
            (ROOT_PROCESS_ID,),
        )
        connection.execute(
            "UPDATE jobs SET status='queued',claimed_by=NULL,claimed_at=NULL "
            "WHERE job_id=?",
            (ROOT_JOB_ID,),
        )


def _claim_root(db_path: Path) -> None:
    with spawn._connect(db_path) as connection, connection:
        connection.execute(
            "UPDATE processes SET status='running',current_job_id=? WHERE process_id=?",
            (ROOT_JOB_ID, ROOT_PROCESS_ID),
        )
        connection.execute(
            "UPDATE jobs SET status='running',claimed_by='test-worker',claimed_at=? "
            "WHERE job_id=?",
            (spawn.TIMESTAMP, ROOT_JOB_ID),
        )


def _holds(db_path: Path, cursor: int) -> bool:
    return _pause_anchor_still_holds(
        db_path=db_path,
        busy_timeout_ms=spawn.BUSY_TIMEOUT_MS,
        process_id=ROOT_PROCESS_ID,
        cursor=cursor,
    )


def test_only_the_live_pause_generation_releases_the_forwarder(
    tmp_path: Path,
) -> None:
    db_path, _context = spawn._runtime(tmp_path)

    first = _pause_root(db_path, session_id="session-1", request_id="request-1")
    assert _holds(db_path, first) is True

    _resume_root(db_path)
    assert _holds(db_path, first) is False

    _claim_root(db_path)
    second = _pause_root(db_path, session_id="session-2", request_id="request-2")
    assert second > first
    # The superseded anchor stays on the stream and must never release again,
    # even though the root is paused once more.
    assert _holds(db_path, first) is False
    assert _holds(db_path, second) is True
