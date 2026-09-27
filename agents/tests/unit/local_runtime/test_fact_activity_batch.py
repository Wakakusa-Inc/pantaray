from __future__ import annotations

import pytest

from pantaray_agents.repositories.fact_activity_batch import (
    split_fact_activity_batch,
)


def test_fact_activity_batch_requires_positive_target() -> None:
    with pytest.raises(ValueError, match="target_total_chars must be positive"):
        split_fact_activity_batch(rows=[], target_total_chars=0)


def test_fact_activity_batch_preserves_initial_and_deferred_order() -> None:
    rows = [
        {"log_id": "log-1", "description": "1234"},
        {"log_id": "log-2", "description": "5678"},
        {"log_id": "log-3", "description": "90"},
    ]

    batch = split_fact_activity_batch(rows=rows, target_total_chars=6)

    assert [row["log_id"] for row in batch.initial_rows] == ["log-1"]
    assert [row["log_id"] for row in batch.deferred_rows] == [
        "log-2",
        "log-3",
    ]


def test_fact_activity_batch_keeps_one_oversized_initial_row() -> None:
    rows = [
        {"log_id": "oversized", "description": "12345"},
        {"log_id": "following", "description": "6"},
    ]

    batch = split_fact_activity_batch(rows=rows, target_total_chars=4)

    assert [row["log_id"] for row in batch.initial_rows] == ["oversized"]
    assert [row["log_id"] for row in batch.deferred_rows] == ["following"]


def test_fact_activity_batch_has_no_deferred_rows_when_all_fit() -> None:
    rows = [
        {"log_id": "log-1", "description": "1234"},
        {"log_id": "log-2", "description": "56"},
    ]

    batch = split_fact_activity_batch(rows=rows, target_total_chars=6)

    assert batch.initial_rows == tuple(rows)
    assert batch.deferred_rows == ()


def test_fact_activity_batch_preserves_all_fifty_candidates() -> None:
    rows = [
        {"log_id": f"log-{index}", "description": "x" * 1_000} for index in range(50)
    ]

    batch = split_fact_activity_batch(rows=rows, target_total_chars=32_000)

    combined = (*batch.initial_rows, *batch.deferred_rows)
    assert combined == tuple(rows)
    assert len(batch.initial_rows) == 32
    assert len(batch.deferred_rows) == 18
