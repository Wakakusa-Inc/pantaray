from __future__ import annotations

import sqlite3

import pytest

from pantaray_agents.local_runtime.runtime.job_control import DeferredLocalJob
from pantaray_agents.tasks.job_retry import defer_local_job_if_retryable


@pytest.mark.asyncio
async def test_defer_local_job_retries_only_the_state_transition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = 0
    delays: list[float] = []

    def _defer(**_kwargs: object) -> None:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise sqlite3.OperationalError("database is locked")

    async def _sleep(delay: float) -> None:
        delays.append(delay)

    monkeypatch.setattr(
        "pantaray_agents.tasks.job_retry.defer_local_job",
        _defer,
    )
    monkeypatch.setattr(
        "pantaray_agents.tasks.job_retry.asyncio.sleep",
        _sleep,
    )

    with pytest.raises(DeferredLocalJob):
        await defer_local_job_if_retryable(
            exc=sqlite3.OperationalError("database is locked"),
            job_id="job-1",
            process_id="process-1",
            process_pending_status="enqueued",
            db_path="runtime.db",
            busy_timeout_ms=1_000,
        )

    assert attempts == 2
    assert delays == [0.1]
