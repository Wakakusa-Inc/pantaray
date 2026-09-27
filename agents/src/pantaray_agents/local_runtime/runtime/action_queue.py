from __future__ import annotations

import json

from pantaray_agents.tasks.types import ActionJobPayload

from .job_enqueue import LocalJobEnqueueRequest
from .job_status import PROCESS_STATUS_ENQUEUED
from .job_types import ACTION_PROCESS_KIND, LOCAL_ACTION_JOB_TYPE


def build_local_action_enqueue_request(
    payload: ActionJobPayload,
    *,
    scheduled_at: str,
    suggestion_id: str | None,
) -> LocalJobEnqueueRequest:
    return {
        "job_id": payload["job_id"],
        "user_id": payload["user_id"],
        "job_type": LOCAL_ACTION_JOB_TYPE,
        "process_id": payload["process_id"],
        "process_kind": ACTION_PROCESS_KIND,
        "process_status": PROCESS_STATUS_ENQUEUED,
        "scheduled_at": scheduled_at,
        "logical_key": payload["action_id"],
        "payload_json": json.dumps(payload, ensure_ascii=False),
        "process_started_at": scheduled_at,
        "process_updated_at": scheduled_at,
        "process_heartbeat_at": scheduled_at,
        "process_next_event_seq": 1,
        "process_suggestion_id": suggestion_id,
        "process_action_id": payload["action_id"],
    }


__all__ = ["build_local_action_enqueue_request"]
