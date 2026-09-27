"""The admission gate: whether the runtime may start new work right now.

An identity change -- a different owner, a different cloud session, a different
LLM or Web route -- runs as a stop barrier: close admission, stop what the old
identity started, swap the identity, open admission (design 6.2 / 7.3). This
module is only the gate; the barrier that turns it is the control socket's.

Closed lasts from recording the cancels to swapping the identity, so every
refusal it causes is retryable and no caller has to hold work for it: the worker
leaves the job queued for its next poll, and the WebSocket handshake is denied
with a status Electron main reconnects after.

The gate is a flag, not a count of what is still running. Waiting for the last
job to converge would hold the new owner's work behind a screen capture that
takes up to 15 seconds, and the safety it would buy is already owned elsewhere:
a claimed job checks its recorded identity against the current one before it
sends and before it publishes (design 6.2).
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from threading import Event
from typing import Final

_ADMITTING: Final[Event] = Event()
_ADMITTING.set()


def admission_is_open() -> bool:
    """Whether new work may start. Read from worker threads and serving loops."""
    return _ADMITTING.is_set()


@contextmanager
def admission_closed() -> Iterator[None]:
    """Close admission for the duration of the block, and open it on the way out.

    A barrier that fails part way still opens the gate, or the runtime would
    claim nothing for the rest of the process. This is a flag and not a count,
    so it must not nest: the inner exit would hand admission back while the
    outer barrier is still swapping. ``stop_barrier.identity_changes_serialized``
    is what keeps that from happening -- every identity change queues behind it,
    from its snapshot through its swap.
    """
    _ADMITTING.clear()
    try:
        yield
    finally:
        _ADMITTING.set()


__all__ = ["admission_closed", "admission_is_open"]
