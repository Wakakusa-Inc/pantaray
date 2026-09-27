"""Local action worker entrypoint."""

from __future__ import annotations

import asyncio
import logging

from pantaray_agents.tasks.action_job_runtime import _run_action_job
from pantaray_agents.tasks.types import ActionJobRuntimePayload

logger = logging.getLogger(__name__)


def run_action_job(job_payload: ActionJobRuntimePayload) -> None:
    try:
        asyncio.run(_run_action_job(job_payload))
    except Exception as exc:  # noqa: BLE001
        logger.exception(
            "Action job failed: process_id=%s action_id=%s error=%s",
            job_payload.get("process_id"),
            job_payload.get("action_id"),
            exc,
        )
        raise


__all__ = ["_run_action_job", "run_action_job"]
