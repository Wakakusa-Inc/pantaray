from __future__ import annotations

import sqlite3

from pantaray_agents.tasks.types import ActionSubagentJobPayload

from .job_enqueue import (
    LocalJobEnqueueRequest,
    LocalJobEnqueueResult,
    enqueue_local_job,
)
from .job_payload_models import serialize_action_subagent_job_payload
from .job_status import PROCESS_STATUS_ENQUEUED
from .job_types import ACTION_SUBAGENT_PROCESS_KIND, LOCAL_ACTION_SUBAGENT_JOB_TYPE


def build_action_subagent_enqueue_request(
    payload: ActionSubagentJobPayload,
    *,
    scheduled_at: str,
) -> LocalJobEnqueueRequest:
    return {
        "job_id": payload["job_id"],
        "user_id": payload["user_id"],
        "job_type": LOCAL_ACTION_SUBAGENT_JOB_TYPE,
        "process_id": payload["process_id"],
        "process_kind": ACTION_SUBAGENT_PROCESS_KIND,
        "process_status": PROCESS_STATUS_ENQUEUED,
        "scheduled_at": scheduled_at,
        "logical_key": payload["job_id"],
        "payload_json": serialize_action_subagent_job_payload(payload),
        "process_started_at": scheduled_at,
        "process_updated_at": scheduled_at,
        "process_heartbeat_at": scheduled_at,
        "process_next_event_seq": 1,
        "process_action_id": payload["action_id"],
        "process_parent_process_id": payload["parent_process_id"],
    }


def enqueue_action_subagent_job_in_connection(
    *,
    connection: sqlite3.Connection,
    payload: ActionSubagentJobPayload,
    scheduled_at: str,
) -> LocalJobEnqueueResult:
    """Insert a child process and job in the caller-owned transaction."""

    return enqueue_local_job(
        connection=connection,
        request=build_action_subagent_enqueue_request(
            payload,
            scheduled_at=scheduled_at,
        ),
    )
