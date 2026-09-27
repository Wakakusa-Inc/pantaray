from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling import action_session_temp_paths
from pantaray_agents.local_runtime.tooling.action_session_temp_paths import (
    ActionSessionTempPathError,
    resolve_action_storage_paths,
    validate_action_storage_component,
)

USER_ID = "user-1"
ACTION_ID = "action-1"


def test_action_storage_paths_are_derived_from_one_canonical_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_base = tmp_path / "first"
    second_base = tmp_path / "second"
    resolved_bases = iter((first_base, second_base))
    call_count = 0

    def resolve_storage_base(*, db_path: Path) -> Path:
        nonlocal call_count
        del db_path
        call_count += 1
        return next(resolved_bases)

    monkeypatch.setattr(
        action_session_temp_paths,
        "resolve_local_runtime_storage_base",
        resolve_storage_base,
    )

    paths = resolve_action_storage_paths(
        db_path=tmp_path / "runtime.db",
        user_id=USER_ID,
        action_id=ACTION_ID,
    )

    expected_root = (
        first_base / "local_runtime_workspaces" / "scratch" / USER_ID / ACTION_ID
    )
    assert call_count == 1
    assert paths.storage_base == first_base
    assert paths.action_root == expected_root
    assert paths.workspace == expected_root / "scratch"
    assert paths.tool_results == expected_root / "tool-results"
    assert paths.session_temp_root == expected_root / "scratch" / ".runtime-temp"


@pytest.mark.parametrize("value", ["", ".", "..", "a/b", "a\\b", "a\0b"])
def test_action_storage_component_rejects_non_component_identity(value: str) -> None:
    with pytest.raises(ActionSessionTempPathError):
        validate_action_storage_component(field_name="identity", value=value)
