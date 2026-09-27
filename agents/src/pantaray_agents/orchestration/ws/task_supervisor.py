from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)


class WsTaskSupervisor:
    """Own, observe, and stop every task bound to one WebSocket session."""

    def __init__(self, *, session_id: str) -> None:
        self._session_id = session_id
        self._tasks: dict[str, asyncio.Task[None]] = {}
        self._closed = False

    @property
    def tasks(self) -> dict[str, asyncio.Task[None]]:
        return self._tasks

    def spawn(
        self,
        *,
        task_key: str,
        coro: Coroutine[object, object, None],
    ) -> asyncio.Task[None] | None:
        if self._closed:
            coro.close()
            return None
        self.cancel(task_key)
        task = asyncio.create_task(coro, name=f"ws:{self._session_id}:{task_key}")
        self._tasks[task_key] = task
        task.add_done_callback(
            lambda completed, key=task_key: self._observe_completion(
                task_key=key,
                task=completed,
            )
        )
        return task

    def cancel(self, task_key: str) -> None:
        task = self._tasks.pop(task_key, None)
        if task is not None and not task.done() and task is not asyncio.current_task():
            task.cancel()

    async def close(self) -> None:
        self._closed = True
        tasks = list(self._tasks.values())
        self._tasks.clear()
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _observe_completion(
        self,
        *,
        task_key: str,
        task: asyncio.Task[None],
    ) -> None:
        if self._tasks.get(task_key) is task:
            self._tasks.pop(task_key, None)
        if task.cancelled():
            return
        exception = task.exception()
        if exception is not None:
            logger.error(
                "WebSocket background task failed: session_id=%s task_key=%s",
                self._session_id,
                task_key,
                exc_info=(type(exception), exception, exception.__traceback__),
            )


__all__ = ["WsTaskSupervisor"]
