from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.memory_update_lock import (
    MemoryUpdateLockConflictError,
    MemoryUpdateLockLease,
)


def test_memory_update_lock_is_scoped_by_user(tmp_path: Path) -> None:
    first = MemoryUpdateLockLease(
        root_path=tmp_path,
        user_id="user-1",
        owner_id="run-1",
    )
    conflicting = MemoryUpdateLockLease(
        root_path=tmp_path,
        user_id="user-1",
        owner_id="run-2",
    )
    other_user = MemoryUpdateLockLease(
        root_path=tmp_path,
        user_id="user-2",
        owner_id="run-3",
    )

    with first:
        with other_user:
            pass
        with pytest.raises(MemoryUpdateLockConflictError):
            with conflicting:
                raise AssertionError("same-user memory lock should conflict")

    with conflicting:
        pass
