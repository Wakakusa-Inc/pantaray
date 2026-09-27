from __future__ import annotations

import asyncio
import logging

import pytest

from pantaray_agents.orchestration.ws.task_supervisor import WsTaskSupervisor


@pytest.mark.asyncio
async def test_task_supervisor_observes_background_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    supervisor = WsTaskSupervisor(session_id="session-1")

    async def _fail() -> None:
        raise RuntimeError("boom")

    with caplog.at_level(logging.ERROR):
        task = supervisor.spawn(task_key="failing", coro=_fail())
        assert task is not None
        await asyncio.sleep(0)
        await asyncio.sleep(0)

    assert supervisor.tasks == {}
    assert "task_key=failing" in caplog.text


@pytest.mark.asyncio
async def test_task_supervisor_awaits_cancellation_on_close() -> None:
    supervisor = WsTaskSupervisor(session_id="session-1")
    stopped = asyncio.Event()

    async def _wait() -> None:
        try:
            await asyncio.Event().wait()
        finally:
            stopped.set()

    supervisor.spawn(task_key="waiting", coro=_wait())
    await asyncio.sleep(0)
    await supervisor.close()

    assert stopped.is_set()
    assert supervisor.tasks == {}
