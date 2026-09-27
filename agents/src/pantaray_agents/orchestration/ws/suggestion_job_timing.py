"""Shared timing constants for suggestion job orchestration."""

from __future__ import annotations

SUGGESTION_JOB_POLL_INTERVAL_SECONDS = 0.25


def suggestion_job_poll_interval_seconds() -> float:
    """Return the validated suggestion job polling interval in seconds."""
    if SUGGESTION_JOB_POLL_INTERVAL_SECONDS <= 0:
        raise ValueError("Invalid SUGGESTION_JOB_POLL_INTERVAL_SECONDS")
    return float(SUGGESTION_JOB_POLL_INTERVAL_SECONDS)
