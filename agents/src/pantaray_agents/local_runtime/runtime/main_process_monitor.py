from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from .runtime_env import MAIN_PROCESS_PID_ENV, read_main_process_pid

logger = logging.getLogger(__name__)

MAIN_PROCESS_CHECK_INTERVAL_SECONDS = 0.5


def _is_process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


async def _monitor_main_process(expected_pid: int) -> None:
    while True:
        await asyncio.sleep(MAIN_PROCESS_CHECK_INTERVAL_SECONDS)
        if _is_process_alive(expected_pid):
            continue
        logger.error(
            "Local runtime helper lost owning main process: main_process_pid=%s",
            expected_pid,
        )
        os._exit(1)


@asynccontextmanager
async def monitor_main_process_lifecycle() -> AsyncIterator[None]:
    # Electron が spawn する helper には localBackendHelperManager.ts が必ず
    # この env を渡す。未設定なのは `python -m pantaray_agents` の単独起動、
    # つまり監視すべき親プロセスが存在しないケースだけなので監視を張らない。
    if os.getenv(MAIN_PROCESS_PID_ENV) is None:
        yield
        return
    monitor_task = asyncio.create_task(_monitor_main_process(read_main_process_pid()))
    try:
        yield
    finally:
        monitor_task.cancel()
        try:
            await monitor_task
        except asyncio.CancelledError:
            pass


__all__ = [
    "MAIN_PROCESS_CHECK_INTERVAL_SECONDS",
    "monitor_main_process_lifecycle",
]
