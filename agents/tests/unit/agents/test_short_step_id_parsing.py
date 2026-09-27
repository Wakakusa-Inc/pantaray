"""short_step_id のパース/生成ユーティリティ検証。

目的:
    - short_step_id の仕様外入力を fail-closed で拒否できること
    - scope（S / G{n}）と local_step_number が正しく解釈できること
"""

from __future__ import annotations

import pytest

from pantaray_agents.agents.action_agent.runtime.handlers.nodes.common import (
    build_short_step_id,
    parse_short_step_id,
    scope_for_goal_id,
)
from pantaray_agents.schema.agent.action import StepType


def test_user_request_short_step_id_uses_uppercase_numbered_suffix() -> None:
    short_step_id = build_short_step_id("S", 1, StepType.USER_REQUEST)

    assert short_step_id == "S-1-USER"
    parsed = parse_short_step_id(short_step_id)
    assert parsed.scope_handle == "S"
    assert parsed.local_step_number == 1
    assert parsed.suffix == "USER"


def test_parse_short_step_id_accepts_supervisor() -> None:
    """Supervisor スコープ（S）がパースできること。"""
    parsed = parse_short_step_id("S-1-THINK")
    assert parsed.scope_handle == "S"
    assert parsed.local_step_number == 1
    assert parsed.suffix == "THINK"


def test_parse_short_step_id_accepts_goal_scope() -> None:
    """G{n} 形式の scope_handle がパースできること。"""
    parsed = parse_short_step_id("G12-34-TOOL")
    assert parsed.scope_handle == "G12"
    assert parsed.local_step_number == 34
    assert parsed.suffix == "TOOL"


@pytest.mark.parametrize(
    "bad",
    [
        "goal_001-1-TOOL",  # legacy scope
        "supervisor-1-THINK",  # legacy scope
        "G0-1-THINK",  # invalid goal scope
        "G1-0-TOOL",  # local_step_number must be > 0
        "S-1-tool",  # wrong suffix casing
        "S-1-user",  # wrong USER suffix casing
        "G1--TOOL",  # missing number
        "G1-abc-THINK",  # not a number
        "S-1",  # missing suffix
        " S-1-THINK",  # leading whitespace
        "S-1-THINK ",  # trailing whitespace
    ],
)
def test_parse_short_step_id_rejects_invalid_format(bad: str) -> None:
    """仕様外の short_step_id は fail-closed で拒否されること。"""
    with pytest.raises(ValueError):
        parse_short_step_id(bad)


def test_scope_for_goal_id_accepts_goal_scope() -> None:
    """goal_id が G{n} 形式で受理されること。"""
    assert scope_for_goal_id("G1") == "G1"
    assert scope_for_goal_id("G10") == "G10"


@pytest.mark.parametrize(
    "bad_goal_id",
    [
        "goal_000",  # legacy format
        "goal_0",  # legacy format
        "goal_001",  # legacy format
        "goal_010",  # legacy format
        "goal_-1",
        "goal_abc",
        "",
    ],
)
def test_scope_for_goal_id_rejects_invalid_goal_id(bad_goal_id: str) -> None:
    """仕様外の goal_id は fail-closed で拒否されること。"""
    with pytest.raises(ValueError):
        scope_for_goal_id(bad_goal_id)
