from __future__ import annotations

import importlib
from types import ModuleType

from pantaray_agents.config_shared import AppConfig

LOCAL_RUNTIME_SETTINGS_MODULE = "pantaray_agents.config_local_runtime"

_active_settings_module_name: str | None = None


def _settings_from_module(module: ModuleType) -> AppConfig:
    raw_settings = getattr(module, "settings", None)
    if not isinstance(raw_settings, dict):
        raise TypeError(f"{module.__name__}.settings must be a dict")
    return raw_settings


def register_active_settings_module(module_name: str) -> None:
    """起動時に有効な設定モジュールを登録する。

    ローカルランタイム以外は受け付けない。Cloud は別配布物として
    自分の設定モジュールを直接読むため、ここを経由しない。
    """

    global _active_settings_module_name
    if module_name != LOCAL_RUNTIME_SETTINGS_MODULE:
        raise ValueError(f"Unsupported settings module: {module_name}")
    _active_settings_module_name = module_name


def clear_active_settings_module() -> None:
    global _active_settings_module_name
    _active_settings_module_name = None


def get_active_settings_module_name() -> str:
    module_name = _active_settings_module_name
    if isinstance(module_name, str) and module_name:
        return module_name
    raise RuntimeError(
        "Active settings module is not registered. "
        "Register it from the application entrypoint before resolving dependencies."
    )


def load_active_settings_module() -> ModuleType:
    return importlib.import_module(get_active_settings_module_name())


def load_active_settings() -> AppConfig:
    return _settings_from_module(load_active_settings_module())
