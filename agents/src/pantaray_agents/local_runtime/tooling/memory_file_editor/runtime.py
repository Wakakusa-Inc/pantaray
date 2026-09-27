from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_artifact_root,
    read_local_runtime_db_config,
)
from pantaray_agents.local_runtime.storage.memory_update_lock import (
    MemoryUpdateLockLease,
)


@dataclass(frozen=True, slots=True)
class LocalMemoryFileEditorRuntime:
    artifact_root: Path
    db_path: Path
    busy_timeout_ms: int

    def acquire_user_update_lock(
        self, *, user_id: str, owner_id: str
    ) -> MemoryUpdateLockLease:
        return MemoryUpdateLockLease(
            root_path=self.artifact_root,
            user_id=user_id,
            owner_id=owner_id,
        )


def build_local_memory_file_editor_runtime() -> LocalMemoryFileEditorRuntime:
    db_path, busy_timeout_ms = read_local_runtime_db_config()
    return LocalMemoryFileEditorRuntime(
        artifact_root=read_local_runtime_artifact_root(),
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )
