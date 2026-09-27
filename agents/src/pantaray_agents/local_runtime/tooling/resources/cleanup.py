from __future__ import annotations

import logging
import os
import signal
from inspect import isawaitable
from pathlib import Path
from typing import TypedDict

logger = logging.getLogger(__name__)


class CleanupFailure(RuntimeError):
    """Raised when privileged runtime cleanup fails."""


class CleanupWarningPayload(TypedDict):
    type: str
    message: str
    target: str


def cleanup_temp_path(
    *, path: Path, failure_message: str
) -> CleanupWarningPayload | None:
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        logger.warning("%s: path=%s error=%s", failure_message, path, exc)
        return {
            "type": "cleanup_warning",
            "message": failure_message,
            "target": str(path),
        }
    return None


async def terminate_process_group(
    *,
    process: object,
    signal_to_send: int,
    failure_message: str,
) -> None:
    pid = _require_process_pid(process=process, failure_message=failure_message)
    _kill_process_group(
        pid=pid,
        signal_to_send=signal_to_send,
        failure_message=failure_message,
    )
    await _wait_process(process)


def terminate_process_group_sync(
    *,
    process: object,
    signal_to_send: int,
    failure_message: str,
) -> None:
    pid = _require_process_pid(process=process, failure_message=failure_message)
    _kill_process_group(
        pid=pid,
        signal_to_send=signal_to_send,
        failure_message=failure_message,
    )
    wait = getattr(process, "wait", None)
    if callable(wait):
        wait_result = wait()
        if isawaitable(wait_result):
            raise CleanupFailure(failure_message)


def _require_process_pid(*, process: object, failure_message: str) -> int:
    pid = getattr(process, "pid", None)
    if not isinstance(pid, int) or pid <= 0:
        raise CleanupFailure(failure_message)
    return pid


def _kill_process_group(
    *,
    pid: int,
    signal_to_send: int,
    failure_message: str,
) -> None:
    try:
        os.killpg(pid, signal_to_send)
    except ProcessLookupError:
        return None
    except OSError as exc:
        logger.exception("%s: pid=%s error=%s", failure_message, pid, exc)
        raise CleanupFailure(failure_message) from exc


async def _wait_process(process: object) -> None:
    wait = getattr(process, "wait", None)
    if callable(wait):
        wait_result = wait()
        if isawaitable(wait_result):
            await wait_result


async def terminate_registered_process(
    *, process: object, failure_message: str
) -> None:
    await terminate_process_group(
        process=process,
        signal_to_send=signal.SIGKILL,
        failure_message=failure_message,
    )
