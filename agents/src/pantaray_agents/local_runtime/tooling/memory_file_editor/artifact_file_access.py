from __future__ import annotations

from pathlib import Path

from pantaray_agents.local_runtime.tooling.repository.workspace_settings import (
    list_workspace_settings,
)

from .registry import ReadableFileRoot


def build_artifact_readable_roots(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
) -> tuple[ReadableFileRoot, ...]:
    settings = list_workspace_settings(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        user_id=user_id,
    )
    return tuple(
        ReadableFileRoot(
            root_id=f"workspace_{folder.folder_id}",
            display_name=folder.display_name,
            path=Path(folder.real_path),
            canonical_path=Path(folder.canonical_real_path),
        )
        for folder in settings.folders
    )
