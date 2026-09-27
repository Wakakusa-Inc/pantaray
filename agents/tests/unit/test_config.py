from __future__ import annotations

import importlib
import sys
import threading
from collections.abc import Iterator

import pytest

from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    load_active_settings,
    register_active_settings_module,
)

_RELOADABLE_CONFIG_MODULE_NAMES = (
    "pantaray_agents.config_local_runtime",
    "pantaray_agents.config",
)


@pytest.fixture(autouse=True)
def _restore_reloaded_config_modules() -> Iterator[None]:
    original_modules = {
        module_name: sys.modules.get(module_name)
        for module_name in _RELOADABLE_CONFIG_MODULE_NAMES
    }
    yield
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _reload_module(module_name: str):
    sys.modules.pop(module_name, None)
    return importlib.import_module(module_name)


def test_local_config_validate_env_vars_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _reload_module("pantaray_agents.config_local_runtime")

    origins, hosts = module.validate_env_vars()

    assert "http://localhost:3001" in origins
    assert "localhost" in hosts


def test_local_config_does_not_require_local_runtime_enabled_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("LOCAL_RUNTIME_ENABLED", raising=False)
    module = _reload_module("pantaray_agents.config_local_runtime")
    origins, hosts = module.validate_env_vars()
    assert "http://localhost:3001" in origins
    assert "localhost" in hosts


def test_local_config_rejects_invalid_llm_proxy_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LLM_PROXY_URL", "ftp://llm-proxy.example.com")
    module = _reload_module("pantaray_agents.config_local_runtime")

    with pytest.raises(ValueError, match="LLM_PROXY_URL"):
        module.validate_env_vars()


def test_local_config_startup_gate_exits_on_invalid_tunables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _reload_module("pantaray_agents.config_local_runtime")

    def _broken_tunables() -> None:
        raise RuntimeError("Invalid local runtime tunables in config_tunables.toml")

    monkeypatch.setattr(module, "load_local_runtime_tunables", _broken_tunables)

    with pytest.raises(SystemExit, match="Invalid local runtime tunables"):
        module.require_valid_startup_config_or_exit()


def test_local_config_get_app_config_reports_local_mode() -> None:
    module = _reload_module("pantaray_agents.config_local_runtime")

    config = module.get_app_config()

    assert config["mode"] == "local_runtime"
    assert config["desktop_updates_bucket"] is None
    assert config["desktop_updates_prefix"] is None


def test_local_config_alias_module_is_local_only() -> None:
    module = _reload_module("pantaray_agents.config")

    assert module.settings["mode"] == "local_runtime"
    assert not any(key.startswith("supabase") for key in module.settings)


def test_load_active_settings_requires_explicit_registration() -> None:
    clear_active_settings_module()

    with pytest.raises(RuntimeError, match="Active settings module is not registered"):
        load_active_settings()


def test_load_active_settings_reads_registered_local_runtime_module() -> None:
    clear_active_settings_module()
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)

    settings = load_active_settings()

    assert settings["mode"] == "local_runtime"


def test_load_active_settings_is_visible_from_worker_thread() -> None:
    clear_active_settings_module()
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)
    result: dict[str, object] = {}

    def read_settings() -> None:
        result["settings"] = load_active_settings()

    worker = threading.Thread(target=read_settings)
    worker.start()
    worker.join()

    settings = result["settings"]
    assert isinstance(settings, dict)
    assert settings["mode"] == "local_runtime"


def test_register_active_settings_module_rejects_cloud_module() -> None:
    """Cloud は別配布物として `pantaray_cloud.config` を直接読む。ここを経由させない。"""

    clear_active_settings_module()

    with pytest.raises(ValueError, match="Unsupported settings module"):
        register_active_settings_module("pantaray_cloud.config")


def test_config_rejects_mock_mode_in_production(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODE_ENV", "production")
    monkeypatch.setenv("USE_MOCKS", "true")
    monkeypatch.setenv("SUPABASE_SECRET_KEY", "test-supabase-secret-key")

    with pytest.raises(ValueError, match="USE_MOCKS must be false"):
        _reload_module("pantaray_agents.config_local_runtime")


def test_local_config_rejects_mock_mode_in_packaged_build(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("NODE_ENV", "development")
    monkeypatch.setenv("USE_MOCKS", "true")
    monkeypatch.setenv("PANTARAY_PACKAGED", "1")

    with pytest.raises(ValueError, match="packaged desktop build"):
        _reload_module("pantaray_agents.config_local_runtime")
