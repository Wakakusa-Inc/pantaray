"""memory_source_policy の型/定数整合性テスト。"""

from typing import get_args

from pantaray_agents.utils.memory_source_policy import (
    MEMORY_SOURCE_ORDER,
    MemorySourceId,
)


def test_memory_source_order_matches_memory_source_id_literal() -> None:
    """MemorySourceId と ORDER の定義ドリフトを検出する。"""
    literal_values = get_args(MemorySourceId)

    assert set(MEMORY_SOURCE_ORDER) == set(literal_values)
    assert len(MEMORY_SOURCE_ORDER) == len(literal_values)
