from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass

from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .job_claim import ClaimedLocalJob


@dataclass(frozen=True)
class LocalJobHandler:
    parse_payload: Callable[[str], object]
    run: Callable[[object], None]


def dispatch_claimed_job(
    *, claimed_job: ClaimedLocalJob, handlers: Mapping[str, LocalJobHandler]
) -> None:
    handler = handlers.get(claimed_job["job_type"])
    if handler is None:
        raise MigrationError(f"unsupported local job type: {claimed_job['job_type']}")
    payload = handler.parse_payload(claimed_job["payload_json"])
    handler.run(payload)
