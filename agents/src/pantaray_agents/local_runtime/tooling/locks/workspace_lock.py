from __future__ import annotations

import fcntl
import hashlib
import json
import os
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

WORKSPACE_LOCK_STORE_SUFFIX = ".workspace-locks"
WORKSPACE_LOCK_FILE_SUFFIX = ".lock.json"


@dataclass(frozen=True, slots=True)
class WorkspaceLockRecord:
    lock_id: str
    tool_invocation_id: str
    execution_session_id: str
    lock_key: str
    locked_path: str
    acquired_at: str


@dataclass(frozen=True, slots=True)
class WorkspaceLockFile:
    lock_path: Path
    record: WorkspaceLockRecord


def workspace_lock_store_path(*, db_path: Path) -> Path:
    return db_path.parent / f"{db_path.name}{WORKSPACE_LOCK_STORE_SUFFIX}"


def workspace_root_lock_path(*, db_path: Path, lock_key: str) -> Path:
    lock_filename = (
        f"{hashlib.sha256(lock_key.encode('utf-8')).hexdigest()}"
        f"{WORKSPACE_LOCK_FILE_SUFFIX}"
    )
    return workspace_lock_store_path(db_path=db_path) / lock_filename


def create_workspace_lock_file(*, lock_file: WorkspaceLockFile) -> None:
    lock_file.lock_path.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_workspace_lock_store(lock_file.lock_path.parent):
        descriptor = os.open(
            lock_file.lock_path,
            os.O_CREAT | os.O_EXCL | os.O_WRONLY,
            0o600,
        )
        try:
            payload = json.dumps(
                {
                    "lock_id": lock_file.record.lock_id,
                    "tool_invocation_id": lock_file.record.tool_invocation_id,
                    "execution_session_id": lock_file.record.execution_session_id,
                    "lock_key": lock_file.record.lock_key,
                    "locked_path": lock_file.record.locked_path,
                    "acquired_at": lock_file.record.acquired_at,
                },
                ensure_ascii=False,
                sort_keys=True,
            ).encode("utf-8")
            os.write(descriptor, payload)
        finally:
            os.close(descriptor)


@contextmanager
def _exclusive_workspace_lock_store(store_path: Path) -> Iterator[None]:
    descriptor = os.open(store_path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        os.close(descriptor)


def read_workspace_lock_record(*, lock_path: Path) -> WorkspaceLockRecord | None:
    try:
        raw_payload = lock_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    payload = json.loads(raw_payload)
    if not isinstance(payload, dict):
        return None
    lock_id = payload.get("lock_id")
    tool_invocation_id = payload.get("tool_invocation_id")
    execution_session_id = payload.get("execution_session_id")
    lock_key = payload.get("lock_key")
    locked_path = payload.get("locked_path")
    acquired_at = payload.get("acquired_at")
    if (
        not isinstance(lock_id, str)
        or not lock_id
        or not isinstance(tool_invocation_id, str)
        or not tool_invocation_id
        or not isinstance(execution_session_id, str)
        or not execution_session_id
        or not isinstance(lock_key, str)
        or not lock_key
        or not isinstance(locked_path, str)
        or not locked_path
        or not isinstance(acquired_at, str)
        or not acquired_at
    ):
        return None
    return WorkspaceLockRecord(
        lock_id=lock_id,
        tool_invocation_id=tool_invocation_id,
        execution_session_id=execution_session_id,
        lock_key=lock_key,
        locked_path=locked_path,
        acquired_at=acquired_at,
    )


def release_workspace_lock_file(
    *,
    lock_path: Path,
    tool_invocation_id: str,
    lock_id: str,
) -> None:
    remove_workspace_lock_file_if_owned(
        lock_path=lock_path,
        tool_invocation_id=tool_invocation_id,
        lock_id=lock_id,
    )


def remove_workspace_lock_file_if_owned(
    *,
    lock_path: Path,
    tool_invocation_id: str,
    lock_id: str,
) -> bool:
    try:
        with _exclusive_workspace_lock_store(lock_path.parent):
            record = read_workspace_lock_record(lock_path=lock_path)
            if record is None:
                return False
            if record.tool_invocation_id != tool_invocation_id:
                return False
            if record.lock_id != lock_id:
                return False
            lock_path.unlink(missing_ok=True)
            return True
    except FileNotFoundError:
        return False


__all__ = [
    "WorkspaceLockFile",
    "WorkspaceLockRecord",
    "create_workspace_lock_file",
    "read_workspace_lock_record",
    "remove_workspace_lock_file_if_owned",
    "release_workspace_lock_file",
    "workspace_lock_store_path",
    "workspace_root_lock_path",
]
