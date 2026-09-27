"""router テスト共通フィクスチャ"""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def configure_router_unit_tests() -> None:
    """router unit test は常時 local runtime 経路を前提にする。"""
