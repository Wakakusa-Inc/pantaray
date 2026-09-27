from __future__ import annotations

import os
import subprocess
import time
from typing import Literal

PROCESS_IDENTITY_READ_ATTEMPTS = 5
PROCESS_IDENTITY_RETRY_INTERVAL_SECONDS = 0.02
ProcessIdentityStatus = Literal["match", "mismatch_or_absent", "unknown"]


def _process_exists(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _read_process_start_signature_once(*, pid: int) -> str | None:
    result = subprocess.run(
        ["ps", "-o", "lstart=", "-p", str(pid)],
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode != 0:
        return None
    signature = result.stdout.strip()
    if not signature:
        return None
    return signature


def read_process_start_signature(*, pid: int) -> str:
    for attempt in range(PROCESS_IDENTITY_READ_ATTEMPTS):
        signature = _read_process_start_signature_once(pid=pid)
        if signature is not None:
            return signature
        if not _process_exists(pid):
            raise ProcessLookupError(
                f"process exited before start signature could be read: pid={pid}"
            )
        if attempt + 1 < PROCESS_IDENTITY_READ_ATTEMPTS:
            time.sleep(PROCESS_IDENTITY_RETRY_INTERVAL_SECONDS)
    raise RuntimeError(f"failed to read process start signature: pid={pid}")


def classify_process_identity(
    *, pid: int, expected_start_signature: str | None
) -> ProcessIdentityStatus:
    if expected_start_signature is None:
        return "unknown" if _process_exists(pid) else "mismatch_or_absent"
    for attempt in range(PROCESS_IDENTITY_READ_ATTEMPTS):
        current_signature = _read_process_start_signature_once(pid=pid)
        if current_signature is not None:
            if current_signature == expected_start_signature:
                return "match"
            return "mismatch_or_absent"
        if not _process_exists(pid):
            return "mismatch_or_absent"
        if attempt + 1 < PROCESS_IDENTITY_READ_ATTEMPTS:
            time.sleep(PROCESS_IDENTITY_RETRY_INTERVAL_SECONDS)
    return "unknown"


__all__ = ["classify_process_identity", "read_process_start_signature"]
