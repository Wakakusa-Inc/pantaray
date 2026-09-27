from __future__ import annotations

import asyncio
import inspect

import pytest
from tests.integration.runtime_dependency_stub import (
    _is_dependency_entrypoint,
    install_runtime_dependency_stub,
)

import pantaray_agents.dependencies as deps
import pantaray_agents.dependencies_memory as memory_deps


def test_install_runtime_dependency_stub_auto_stubs_dependency_entrypoints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    originals = {
        name: value
        for name, value in inspect.getmembers(deps)
        if _is_dependency_entrypoint(name, value)
    }
    for name, value in originals.items():
        monkeypatch.setattr(deps, name, value, raising=False)

    stubbed = install_runtime_dependency_stub(monkeypatch=monkeypatch)

    with pytest.raises(AssertionError, match="Test must patch this dependency"):
        stubbed.get_local_action_repository()

    with pytest.raises(AssertionError, match="Test must patch this dependency"):
        asyncio.run(memory_deps.get_activity_summary_agent())
