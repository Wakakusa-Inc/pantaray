from __future__ import annotations

import importlib
import inspect
from types import ModuleType
from typing import Any

import pytest

_DEPENDENCY_ENTRYPOINT_PREFIXES = (
    "get_",
    "create_",
    "validate_",
)
_DEPENDENCY_ENTRYPOINT_NAMES = ("is_mock_mode",)


def _is_dependency_entrypoint(name: str, value: object) -> bool:
    if not callable(value):
        return False
    return name.startswith(_DEPENDENCY_ENTRYPOINT_PREFIXES) or (
        name in _DEPENDENCY_ENTRYPOINT_NAMES
    )


def install_runtime_dependency_stub(*, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    module = importlib.import_module("pantaray_agents.dependencies")

    async def _missing_async(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Test must patch this dependency before use")

    def _missing_sync(*_args: Any, **_kwargs: Any) -> Any:
        raise AssertionError("Test must patch this dependency before use")

    memory_module = importlib.import_module("pantaray_agents.dependencies_memory")
    for target in (module, memory_module):
        for name, value in inspect.getmembers(target):
            if not _is_dependency_entrypoint(name, value):
                continue
            if inspect.iscoroutinefunction(value):
                monkeypatch.setattr(target, name, _missing_async)
                continue
            monkeypatch.setattr(target, name, _missing_sync)
    return module
