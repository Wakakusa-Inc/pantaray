from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.artifacts.bootstrap import (
    bootstrap_local_artifact_store,
)
from pantaray_agents.local_runtime.artifacts.paths import (
    required_artifact_subdirectories,
    resolve_artifact_path,
)
from pantaray_agents.local_runtime.storage.migrations import MigrationError


def test_bootstrap_local_artifact_store_creates_required_directories(
    tmp_path: Path,
) -> None:
    root_path = tmp_path / "artifacts"

    layout = bootstrap_local_artifact_store(root_path=root_path)

    assert layout.root_path == root_path.resolve()
    for dirname in required_artifact_subdirectories():
        assert (layout.root_path / dirname).is_dir()


def test_resolve_artifact_path_rejects_traversal(tmp_path: Path) -> None:
    root_path = tmp_path / "artifacts"
    bootstrap_local_artifact_store(root_path=root_path)

    with pytest.raises(MigrationError, match="forbidden traversal"):
        resolve_artifact_path(
            root_path=root_path,
            relative_path="../escape.txt",
        )
