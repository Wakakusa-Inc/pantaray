"""Process event persistence errors shared by local runtime workers."""

from __future__ import annotations


class ProcessEventAppendError(RuntimeError):
    """process event append failed."""


class ProcessTerminalStateError(RuntimeError):
    """process terminal state update failed."""


__all__ = [
    "ProcessEventAppendError",
    "ProcessTerminalStateError",
]
