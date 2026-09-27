from __future__ import annotations

import importlib
import sys

import pytest
from fastapi.testclient import TestClient

from pantaray_agents.settings_loader import get_active_settings_module_name


def _drop_modules(*module_names: str) -> None:
    for module_name in module_names:
        sys.modules.pop(module_name, None)


def test_local_role_boundary_import_smoke_without_provider_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LOCAL_RUNTIME_ENABLED", "true")
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("TAVILY_API_KEY", raising=False)

    _drop_modules(
        "pantaray_agents.entrypoints.main_local",
        "pantaray_agents.app.local_app",
        "pantaray_agents.config",
        "pantaray_agents.config_local_runtime",
        "pantaray_agents.config_shared",
    )
    local_app = importlib.import_module("pantaray_agents.app.local_app")
    monkeypatch.setattr(local_app, "start_local_runtime_if_enabled", lambda: None)
    monkeypatch.setattr(local_app, "stop_local_runtime_if_enabled", lambda: None)

    app = local_app.create_local_app()
    with TestClient(app) as client:
        response = client.get("/health")
        assert (
            get_active_settings_module_name() == "pantaray_agents.config_local_runtime"
        )
    assert response.status_code == 200
    with pytest.raises(RuntimeError, match="Active settings module is not registered"):
        get_active_settings_module_name()
