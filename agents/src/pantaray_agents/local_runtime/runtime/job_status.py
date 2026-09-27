from __future__ import annotations

from typing import Final, Literal

JOB_STATUS_QUEUED: Final[Literal["queued"]] = "queued"
JOB_STATUS_RUNNING: Final[Literal["running"]] = "running"
JOB_STATUS_PAUSED: Final[Literal["paused"]] = "paused"
JOB_STATUS_RETRYABLE_ERROR: Final[Literal["retryable_error"]] = "retryable_error"
JOB_STATUS_BLOCKED: Final[Literal["blocked"]] = "blocked"
JOB_STATUS_COMPLETED: Final[Literal["completed"]] = "completed"
JOB_STATUS_FAILED: Final[Literal["failed"]] = "failed"
JOB_STATUS_ABANDONED: Final[Literal["abandoned"]] = "abandoned"
JOB_STATUS_CANCELED: Final[Literal["canceled"]] = "canceled"

ACTIVE_DEDUPE_JOB_STATUSES: Final[tuple[str, ...]] = (
    JOB_STATUS_QUEUED,
    JOB_STATUS_RUNNING,
    JOB_STATUS_RETRYABLE_ERROR,
)

FINALIZABLE_JOB_STATUSES: Final[tuple[str, ...]] = (
    JOB_STATUS_COMPLETED,
    JOB_STATUS_FAILED,
    JOB_STATUS_ABANDONED,
    JOB_STATUS_CANCELED,
    JOB_STATUS_BLOCKED,
)

PROCESS_STATUS_ENQUEUED: Final[Literal["enqueued"]] = "enqueued"
