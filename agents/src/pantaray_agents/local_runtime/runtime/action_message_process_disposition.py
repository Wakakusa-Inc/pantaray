"""Classify the process fence for one existing Action conversation."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Literal

from pantaray_agents.action_status import ActionTerminalStatus
from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .action_message_process_fence import (
    ActionLogicalRunLineage,
    resolve_action_process_lineage_in_connection,
)

type ActionProcessDisposition = Literal[
    "idle", "active", "approval_paused", "normal_terminal", "canceled", "stale"
]


@dataclass(frozen=True, slots=True)
class ActionProcessDispositionResult:
    disposition: ActionProcessDisposition
    required_action_status: ActionTerminalStatus | None


# The canonical Action terminal transaction commits Action, job, and process together;
# every other pair is producer corruption, not a transient state to normalize here.
_CANONICAL_STATUS_PAIRS: dict[tuple[str, str], ActionProcessDispositionResult] = {
    ("enqueued", "queued"): ActionProcessDispositionResult("active", None),
    ("running", "running"): ActionProcessDispositionResult("active", None),
    ("paused", "paused"): ActionProcessDispositionResult("approval_paused", None),
    ("completed", "completed"): ActionProcessDispositionResult(
        "normal_terminal", "success"
    ),
    ("failed", "failed"): ActionProcessDispositionResult("normal_terminal", "error"),
    ("canceled", "canceled"): ActionProcessDispositionResult("canceled", "canceled"),
}
ACTIVE_ACTION_DISPOSITIONS = frozenset({"active", "approval_paused"})
_IDLE = ActionProcessDispositionResult("idle", None)
_STALE = ActionProcessDispositionResult("stale", None)


@dataclass(frozen=True, slots=True)
class _ProcessInventoryRow:
    process_id: str
    status: str


@dataclass(frozen=True, slots=True)
class _JobInventoryRow:
    job_id: str
    process_id: str
    status: str


@dataclass(frozen=True, slots=True)
class _ActionLogicalRun:
    lineage: ActionLogicalRunLineage
    process_status: str
    job_status: str


def classify_action_process_disposition_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    expected_process_id: str | None,
) -> ActionProcessDispositionResult:
    """Resolve and classify one Action's immutable process fence without mutation."""

    return _classify_process_fence(
        runs=_load_action_logical_runs(
            connection=connection,
            user_id=user_id,
            action_id=action_id,
        ),
        expected_process_id=expected_process_id,
    )


def _load_action_logical_runs(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
) -> tuple[_ActionLogicalRun, ...]:
    processes = _load_process_inventory(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
    )
    lineages = tuple(
        resolve_action_process_lineage_in_connection(
            connection=connection,
            user_id=user_id,
            action_id=action_id,
            process_id=process.process_id,
        )
        for process in processes
    )
    job_by_process_id: dict[str, _JobInventoryRow] = {}
    for job in _load_job_inventory(
        connection=connection,
        user_id=user_id,
        action_id=action_id,
    ):
        if job.process_id in job_by_process_id:
            raise MigrationError("Action process does not have exactly one owning job")
        job_by_process_id[job.process_id] = job
    if {process.process_id for process in processes} != set(job_by_process_id):
        raise MigrationError("Action process and job inventories are inconsistent")

    runs: list[_ActionLogicalRun] = []
    for process, lineage in zip(processes, lineages, strict=True):
        job = job_by_process_id[process.process_id]
        if lineage.job_id != job.job_id:
            raise MigrationError("Action lineage job identity is inconsistent")
        runs.append(
            _ActionLogicalRun(
                lineage=lineage,
                process_status=process.status,
                job_status=job.status,
            )
        )
    return tuple(runs)


def _load_process_inventory(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
) -> tuple[_ProcessInventoryRow, ...]:
    rows = connection.execute(
        """
        SELECT process_id, status
        FROM processes
        WHERE user_id = ? AND action_id = ? AND kind = 'action'
        ORDER BY process_id
        """,
        (user_id, action_id),
    ).fetchall()
    return tuple(
        _ProcessInventoryRow(
            process_id=require_disposition_text(
                row["process_id"], field_name="process_id"
            ),
            status=require_disposition_text(row["status"], field_name="process status"),
        )
        for row in rows
    )


def _load_job_inventory(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
) -> tuple[_JobInventoryRow, ...]:
    rows = connection.execute(
        """
        SELECT job_id, process_id, status
        FROM jobs
        WHERE user_id = ? AND logical_key = ? AND job_type = 'execute_action'
        ORDER BY job_id
        """,
        (user_id, action_id),
    ).fetchall()
    return tuple(
        _JobInventoryRow(
            job_id=require_disposition_text(row["job_id"], field_name="job_id"),
            process_id=require_disposition_text(
                row["process_id"], field_name="job process_id"
            ),
            status=require_disposition_text(row["status"], field_name="job status"),
        )
        for row in rows
    )


def _classify_process_fence(
    *,
    runs: tuple[_ActionLogicalRun, ...],
    expected_process_id: str | None,
) -> ActionProcessDispositionResult:
    if not runs:
        return _IDLE if expected_process_id is None else _STALE

    run_by_root_id = {run.lineage.root_process_id: run for run in runs}
    if len({run.lineage.root_accepted_sequence for run in runs}) != len(runs):
        raise MigrationError("Action logical runs share a root accepted_sequence")
    latest_root_id = max(
        run_by_root_id,
        key=lambda root_process_id: (
            run_by_root_id[root_process_id].lineage.root_accepted_sequence
        ),
    )
    active_roots = [
        root_process_id
        for root_process_id, run in run_by_root_id.items()
        if _run_disposition(run).disposition in ACTIVE_ACTION_DISPOSITIONS
    ]
    if active_roots and active_roots != [latest_root_id]:
        raise MigrationError("Only the latest Action logical run may be active")

    if expected_process_id is None:
        return _STALE if active_roots else _IDLE
    if expected_process_id != latest_root_id:
        return _STALE
    return _run_disposition(run_by_root_id[latest_root_id])


def _run_disposition(run: _ActionLogicalRun) -> ActionProcessDispositionResult:
    return classify_action_status_pair(run.process_status, run.job_status)


def classify_action_status_pair(
    process_status: str, job_status: str
) -> ActionProcessDispositionResult:
    disposition = _CANONICAL_STATUS_PAIRS.get((process_status, job_status))
    if disposition is None:
        raise MigrationError("Action process and job status pair is noncanonical")
    return disposition


def require_disposition_text(value: object, *, field_name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"Action disposition {field_name} is incomplete")
    return value


__all__ = [
    "ACTIVE_ACTION_DISPOSITIONS",
    "ActionProcessDisposition",
    "ActionProcessDispositionResult",
    "classify_action_process_disposition_in_connection",
    "classify_action_status_pair",
    "require_disposition_text",
]
