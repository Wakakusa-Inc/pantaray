from __future__ import annotations

import pytest
from pydantic import ValidationError

from pantaray_agents.schema.agent.base import TaskStatusType
from pantaray_agents.schema.agent.streaming import ActionStreamEndData, StreamEndData
from pantaray_agents.utils.streaming_helpers import (
    coerce_task_status,
    make_stream_end_for_suggestion,
)


def test_coerce_task_status_maps_queued_to_processing() -> None:
    """外部に queued を出さないため、queued は processing に丸められること。"""
    assert coerce_task_status("queued") == TaskStatusType.PROCESSING


def test_stream_end_data_rejects_queued_status() -> None:
    """StreamEndData は queued を受け付けない（外部APIへ出さないため）。"""
    with pytest.raises(ValidationError):
        StreamEndData(
            suggestion_id="sug-1",
            has_suggestion=True,
            user_id="user-1",
            completed_at="2025-01-01T00:00:00Z",
            status="queued",
            total_chunks=0,
            duration_ms=1,
        )


def test_action_stream_end_data_rejects_queued_status() -> None:
    """ActionStreamEndData は queued を受け付けない（外部APIへ出さないため）。"""
    with pytest.raises(ValidationError):
        ActionStreamEndData(
            action_id="act-1",
            suggestion_id="sug-1",
            user_id="user-1",
            completed_at="2025-01-01T00:00:00Z",
            status="queued",
            total_chunks=0,
            duration_ms=1,
        )


def test_make_stream_end_for_suggestion_outputs_json_serializable_status() -> None:
    """StreamEndData は model_dump 経由で JSON 化できる（Enumが残らない）こと。"""
    end = make_stream_end_for_suggestion(
        suggestion_id="sug-1",
        user_id="user-1",
        has_suggestion=True,
        total_chunks=1,
        status=coerce_task_status("queued"),
        duration_ms=123,
    )
    dumped = end.model_dump()
    assert dumped["status"] == "processing"
