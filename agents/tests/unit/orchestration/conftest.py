"""orchestration テスト共通フィクスチャ"""

from __future__ import annotations

import pytest

from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    register_active_settings_module,
)


@pytest.fixture(autouse=True)
def configure_orchestration_unit_tests() -> None:
    """orchestration unit test は常時 local runtime 経路を前提にする。"""
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)
    yield
    clear_active_settings_module()
