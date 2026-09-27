"""Process-local stored-context access, read confirmation and publication.

Callers hold a turn only for the boundary they linearize, never while awaiting
model responses. source_transport owns the HTTP send-start boundary.
"""

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from concurrent.futures import Future
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from threading import Lock
from uuid import UUID, uuid4

from pantaray_agents.schema.context_source import SourceBinding


class SourceInvalidated(RuntimeError):
    """Access to this user's recorded context has been revoked."""


@dataclass(frozen=True)
class ActiveSource:
    """Read permit and its original grant provenance.

    Recorder epochs and policies can advance while the same store remains readable.
    The live recorder state is owned by SourceControl, not this immutable grant.
    """

    binding: SourceBinding
    token: UUID = field(default_factory=uuid4)


class SourceGate:
    def __init__(self) -> None:
        self._lock = Lock()
        self._waiters: deque[Future[None]] = deque()
        self._active: dict[str, ActiveSource] = {}
        self._tasks: dict[UUID, dict[asyncio.Task[object], int]] = {}

    @asynccontextmanager
    async def turn(self) -> AsyncIterator[None]:
        own: Future[None] = Future()
        with self._lock:
            self._waiters.append(own)
            if len(self._waiters) == 1:
                own.set_result(None)
        try:
            await asyncio.shield(asyncio.wrap_future(own))
            yield
        finally:
            with self._lock:
                was_head = self._waiters[0] is own
                self._waiters.remove(own)
                # Complete a cancelled waiter's wrapper without chaining exits.
                # Only the current head can grant the next turn.
                own.cancel()
                if was_head and self._waiters:
                    self._waiters[0].set_result(None)

    def current(self, user_id: str) -> ActiveSource | None:
        """Read under turn(), like all permit state operations."""
        return self._active.get(user_id)

    def require(self, source: ActiveSource) -> None:
        """Check the full binding AND volatile token while holding turn()."""
        if self.current(source.binding.user_id) != source:
            raise SourceInvalidated("context source was invalidated")

    def activate(self, binding: SourceBinding) -> None:
        """Keep the read grant across same-store recorder generations.

        Called under turn(), only after the durable transition commits. A changed
        store revokes in-flight work before a new grant is issued.
        """
        current = self.current(binding.user_id)
        if current is not None and current.binding.store_id == binding.store_id:
            return
        self.revoke(binding.user_id)
        self._active[binding.user_id] = ActiveSource(binding)

    def revoke(self, user_id: str) -> None:
        """Called under turn(); task cleanup uses the same short native lock."""
        previous = self._active.pop(user_id, None)
        if previous is not None:
            with self._lock:
                for task in self._tasks.get(previous.token, {}):
                    task.get_loop().call_soon_threadsafe(
                        self._cancel_tracked, previous.token, task
                    )

    def _cancel_tracked(self, token: UUID, task: asyncio.Task[object]) -> None:
        # The operation may have exited before its loop receives the callback.
        # Do not cancel a subsequent operation running in the same Task.
        with self._lock:
            if task in self._tasks.get(token, {}):
                task.cancel()

    @asynccontextmanager
    async def guard(self, source: ActiveSource) -> AsyncIterator[None]:
        async with self.turn():
            self.require(source)
            yield

    @asynccontextmanager
    async def track(self, source: ActiveSource) -> AsyncIterator[None]:
        """Cancel an in-flight source operation on access revocation.

        Registration does not mean a network request has started. The caller
        must also guard its read/send/publication boundary.
        """
        task = asyncio.current_task()
        assert task is not None  # An async context manager runs in a Task.
        async with self.guard(source):
            with self._lock:
                tasks = self._tasks.setdefault(source.token, {})
                tasks[task] = tasks.get(task, 0) + 1
        try:
            yield
        finally:
            with self._lock:
                tasks = self._tasks[source.token]
                tasks[task] -= 1
                if not tasks[task]:
                    del tasks[task]
                if not tasks:
                    del self._tasks[source.token]
