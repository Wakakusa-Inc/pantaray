from __future__ import annotations

from pathlib import Path

from pantaray_agents.tasks.types import ActionJobRuntimePayload

from ..storage.migrations import MigrationError
from .job_claim import (
    PROCESS_RUNTIME_STATUS,
    claim_next_pending_job,
    finalize_local_job,
    has_pending_job,
)
from .job_payload_models import parse_action_job_payload_json
from .job_status import JOB_STATUS_CANCELED, JOB_STATUS_COMPLETED

LOCAL_ACTION_JOB_TYPE = "execute_action"
ACTION_PROCESS_STATUS_ENQUEUED: PROCESS_RUNTIME_STATUS = "enqueued"
ACTION_PROCESS_STATUS_RUNNING: PROCESS_RUNTIME_STATUS = "running"
ACTION_PROCESS_STATUS_COMPLETED: PROCESS_RUNTIME_STATUS = "completed"
ACTION_PROCESS_STATUS_CANCELED: PROCESS_RUNTIME_STATUS = "canceled"


def claim_next_pending_action_job(
    *, db_path: Path, busy_timeout_ms: int, owner_user_id: str, claimed_by: str
) -> ActionJobRuntimePayload | None:
    claimed = claim_next_pending_job(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        job_type=LOCAL_ACTION_JOB_TYPE,
        owner_user_id=owner_user_id,
        claimed_by=claimed_by,
        process_running_status=ACTION_PROCESS_STATUS_RUNNING,
        expected_process_pending_status=ACTION_PROCESS_STATUS_ENQUEUED,
    )
    if claimed is None:
        return None
    return parse_action_job_payload_json(claimed["payload_json"])


def finalize_local_action_job(
    *, db_path: Path, busy_timeout_ms: int, job_id: str, succeeded: bool
) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    if not job_id.strip():
        raise MigrationError("job_id must not be empty")

    target_status = JOB_STATUS_COMPLETED if succeeded else JOB_STATUS_CANCELED
    finalize_local_job(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        job_id=job_id,
        final_status=target_status,
        process_final_status=(
            ACTION_PROCESS_STATUS_COMPLETED
            if succeeded
            else ACTION_PROCESS_STATUS_CANCELED
        ),
    )


def has_pending_action_job(*, db_path: Path, busy_timeout_ms: int) -> bool:
    return has_pending_job(
        db_path=str(db_path),
        busy_timeout_ms=busy_timeout_ms,
        job_type=LOCAL_ACTION_JOB_TYPE,
    )
