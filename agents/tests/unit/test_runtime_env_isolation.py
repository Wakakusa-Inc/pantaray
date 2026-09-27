"""`tests/conftest.py` が用意する既定 runtime パスの隔離を検証する。

既定が固定 /tmp パスだと、別 worktree / 別インタプリタで同時に走る pytest が
app runtime manifest・sqlite・lock を互いに上書きし、`verify_app_runtime_python`
が無関係なテストを大量に落とす（実際に数百件の偽失敗を観測済み）。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from pantaray_agents.local_runtime.app_runtime_verification import (
    LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV,
    load_app_runtime_manifest,
    verify_app_runtime_python,
)

_SESSION_SCOPED_PATH_ENVS = (
    "LOCAL_DB_PATH",
    "LOCAL_ARTIFACT_ROOT",
    "LOCAL_RUNTIME_LOCK_PATH",
    "LOG_FILE_PATH",
)


def test_default_runtime_paths_are_private_to_this_pytest_session() -> None:
    manifest_path = Path(os.environ[LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV])
    session_root = manifest_path.parent
    assert session_root != Path("/tmp")
    for env_name in _SESSION_SCOPED_PATH_ENVS:
        assert Path(os.environ[env_name]).parent == session_root

    manifest = load_app_runtime_manifest(manifest_path=manifest_path)
    assert (
        verify_app_runtime_python(manifest=manifest) == Path(sys.executable).resolve()
    )
