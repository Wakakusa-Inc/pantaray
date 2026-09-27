from __future__ import annotations

import json

from pantaray_agents.tasks.types import SuggestionJobPayload

from .job_enqueue import LocalJobEnqueueRequest
from .job_status import PROCESS_STATUS_ENQUEUED
from .job_types import LOCAL_SUGGESTION_JOB_TYPE, SUGGESTION_PROCESS_KIND


def build_local_suggestion_enqueue_request(
    payload: SuggestionJobPayload,
) -> LocalJobEnqueueRequest:
    return {
        "job_id": payload["job_id"],
        "user_id": payload["user_id"],
        "job_type": LOCAL_SUGGESTION_JOB_TYPE,
        "process_id": payload["process_id"],
        "process_kind": SUGGESTION_PROCESS_KIND,
        "process_status": PROCESS_STATUS_ENQUEUED,
        "scheduled_at": payload["enqueued_at"],
        "logical_key": payload["suggestion_id"],
        "payload_json": json.dumps(payload, ensure_ascii=False),
        "process_started_at": payload["enqueued_at"],
        "process_updated_at": payload["enqueued_at"],
        "process_heartbeat_at": payload["enqueued_at"],
        "process_next_event_seq": 1,
        "process_suggestion_id": payload["suggestion_id"],
    }
