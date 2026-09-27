from __future__ import annotations

import hashlib
import json
import platform
import sys
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.app_runtime_verification import (
    LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV,
)
from pantaray_agents.local_runtime.runtime.bootstrap import (
    LLM_PROXY_URL_ENV,
    LOCAL_ARTIFACT_ROOT_ENV,
    WEB_TOOLS_PROXY_URL_ENV,
)
from pantaray_agents.local_runtime.runtime.initialization import (
    initialize_local_runtime,
    release_initialized_local_runtime,
)
from pantaray_agents.local_runtime.runtime.runtime_env import (
    HELPER_INSTANCE_ID_ENV,
    MAIN_PROCESS_PID_ENV,
)
from pantaray_agents.local_runtime.runtime.worker_daemon import (
    start_local_action_worker_daemon,
)


def set_minimum_local_runtime_env(
    *, monkeypatch: pytest.MonkeyPatch, db_path: Path, tmp_path: Path
) -> None:
    manifest_path = tmp_path / "app-runtime-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "python_path": str(Path(sys.executable).resolve()),
                "python_version": platform.python_version(),
                "python_sha256": hashlib.sha256(
                    Path(sys.executable).read_bytes()
                ).hexdigest(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("LOCAL_DB_PATH", str(db_path))
    monkeypatch.setenv("LOCAL_DB_BUSY_TIMEOUT_MS", "1000")
    monkeypatch.setenv(LOCAL_ARTIFACT_ROOT_ENV, str(tmp_path / "artifacts"))
    monkeypatch.setenv(HELPER_INSTANCE_ID_ENV, "helper-test-instance")
    monkeypatch.setenv(LLM_PROXY_URL_ENV, "https://llm-proxy.example.com")
    monkeypatch.setenv(MAIN_PROCESS_PID_ENV, "99999")
    monkeypatch.setenv(WEB_TOOLS_PROXY_URL_ENV, "https://search-proxy.example.com")
    monkeypatch.setenv(LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV, str(manifest_path))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)


def start_worker() -> None:
    initialized = initialize_local_runtime()
    try:
        start_local_action_worker_daemon(runtime_process_lock=initialized.lock_lease)
    except Exception:
        release_initialized_local_runtime(initialized)
        raise
