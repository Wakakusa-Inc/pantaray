from __future__ import annotations

from pathlib import Path

import pytest

from pantaray_agents.config_tunables import (
    LOCAL_RUNTIME_TUNABLES_PATH,
    load_local_runtime_tunables,
    load_tunables_file,
)


def _tunables_with(tmp_path: Path, old: str, new: str) -> Path:
    """checked-in TOML の 1 箇所だけを差し替えた一時ファイルを作る。"""

    text = LOCAL_RUNTIME_TUNABLES_PATH.read_text(encoding="utf-8")
    assert old in text, f"fixture text not found: {old!r}"
    target = tmp_path / "config_tunables.toml"
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return target


def test_checked_in_tunables_match_shipped_values() -> None:
    tunables = load_local_runtime_tunables()

    assert tunables.action_agent.max_parallel_tool_calls == 3
    assert (
        tunables.artifact_paths.long_term_insight_storage_path_template
        == "users/{user_id}/insights/long_term.md"
    )


def test_missing_file_fails_with_path(tmp_path: Path) -> None:
    absent = tmp_path / "absent.toml"

    with pytest.raises(RuntimeError, match=str(absent)):
        load_tunables_file(absent)


def test_invalid_toml_fails(tmp_path: Path) -> None:
    target = tmp_path / "config_tunables.toml"
    target.write_text("[action_agent\n", encoding="utf-8")

    with pytest.raises(RuntimeError, match="Invalid TOML"):
        load_tunables_file(target)


def test_missing_key_fails(tmp_path: Path) -> None:
    target = _tunables_with(tmp_path, "max_steps = 300\n", "")

    with pytest.raises(RuntimeError, match="max_steps"):
        load_tunables_file(target)


def test_unknown_key_fails(tmp_path: Path) -> None:
    target = _tunables_with(
        tmp_path, "[artifact_paths]\n", "[artifact_paths]\nunknown_knob = 1\n"
    )

    with pytest.raises(RuntimeError, match="unknown_knob"):
        load_tunables_file(target)


def test_wrong_type_fails(tmp_path: Path) -> None:
    target = _tunables_with(
        tmp_path, "max_parallel_tool_calls = 3", 'max_parallel_tool_calls = "3"'
    )

    with pytest.raises(RuntimeError, match="max_parallel_tool_calls"):
        load_tunables_file(target)


def test_out_of_range_fails(tmp_path: Path) -> None:
    target = _tunables_with(tmp_path, "max_steps = 300", "max_steps = 0")

    with pytest.raises(RuntimeError, match="greater than 0"):
        load_tunables_file(target)


def test_storage_path_template_requires_user_id(tmp_path: Path) -> None:
    target = _tunables_with(
        tmp_path,
        'structured_facts_storage_path_template = "users/{user_id}/facts/'
        'structured_facts.md"',
        'structured_facts_storage_path_template = "facts/structured_facts.md"',
    )

    with pytest.raises(RuntimeError, match=r"\{user_id\}"):
        load_tunables_file(target)
