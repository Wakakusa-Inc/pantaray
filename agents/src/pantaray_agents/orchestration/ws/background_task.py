from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

logger = logging.getLogger(__name__)


def spawn_ws_background_task(
    *,
    owner: object,
    task_key: str,
    coro: Coroutine[object, object, None],
) -> asyncio.Task[None] | None:
    spawn = getattr(owner, "_spawn_background_task", None)
    if callable(spawn):
        task = spawn(task_key=task_key, coro=coro)
        return task if isinstance(task, asyncio.Task) else None
    task = asyncio.create_task(coro, name=f"ws:{task_key}")
    task.add_done_callback(_observe_background_task)
    return task


def _observe_background_task(task: asyncio.Task[None]) -> None:
    if task.cancelled():
        return
    exception = task.exception()
    if exception is not None:
        logger.error(
            "Unsupervised WebSocket background task failed: task_name=%s",
            task.get_name(),
            exc_info=(type(exception), exception, exception.__traceback__),
        )


__all__ = ["spawn_ws_background_task"]
