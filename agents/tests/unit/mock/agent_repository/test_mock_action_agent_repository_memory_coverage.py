from __future__ import annotations

import pytest

from pantaray_agents.schema.repositories.repository import RepositoryErrorKind

from .shared import UTC, MockActionAgentRepository, StatusType, datetime, timedelta


async def _save_memory_artifact(
    repo: MockActionAgentRepository,
    *,
    artifact_id: str,
    user_id: str,
    source_type: str,
    logical_created_at: str,
    logical_updated_at: str,
) -> None:
    await repo.save_data(
        "memory_artifacts",
        {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "source_type": source_type,
            "source_record_id": f"record-{artifact_id}",
            "root_path": f"artifacts/{source_type}/{artifact_id}",
            "content_sha256": f"sha-{artifact_id}",
            "logical_created_at": logical_created_at,
            "logical_updated_at": logical_updated_at,
            "indexed_at": logical_updated_at,
        },
    )


async def _save_memory_artifact_projection(
    repo: MockActionAgentRepository,
    *,
    artifact_id: str,
    file_id: str,
    block_id: str,
    updated_at: str,
) -> None:
    await repo.save_data(
        "memory_artifact_files",
        {
            "file_id": file_id,
            "artifact_id": artifact_id,
            "relative_path": "index.md",
            "sha256": f"sha-{file_id}",
            "byte_size": 100,
            "mime_type": "text/markdown",
            "updated_at": updated_at,
        },
    )
    await repo.save_data(
        "memory_artifact_blocks",
        {
            "block_id": block_id,
            "file_id": file_id,
            "block_kind": "paragraph",
            "heading_path": "Root",
            "block_index": 0,
            "search_text": "Body",
            "preview_text": "Body",
        },
    )


@pytest.mark.asyncio
async def test_memory_source_coverage_snapshot_applies_artifact_and_status_policy() -> (
    None
):
    repo = MockActionAgentRepository()
    user_id = "user-coverage"
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    old_iso = (now - timedelta(days=10)).isoformat()
    near_iso = (now - timedelta(minutes=10)).isoformat()

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-long-valid",
        user_id=user_id,
        source_type="long_term_insight",
        logical_created_at=near_iso,
        logical_updated_at=near_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-long-valid",
        file_id="artifact-long-file-valid",
        block_id="artifact-long-block-valid",
        updated_at=near_iso,
    )

    await repo.save_data(
        "insights",
        {
            "insight_id": "ins-empty",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "created_at": near_iso,
            "updated_at": near_iso,
            "short_term_insight_data": "valid-short",
        },
    )
    await repo.save_data(
        "insights",
        {
            "insight_id": "ins-valid",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "created_at": near_iso,
            "updated_at": near_iso,
            "short_term_insight_data": "valid-short",
        },
    )

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-facts-valid",
        user_id=user_id,
        source_type="facts",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-facts-valid",
        file_id="artifact-facts-file-valid",
        block_id="artifact-facts-block-valid",
        updated_at=now_iso,
    )

    await repo.save_data(
        "suggestions",
        {
            "suggestion_id": "sug-processing",
            "user_id": user_id,
            "created_at": near_iso,
            "status": StatusType.PROCESSING.value,
        },
    )
    await repo.save_data(
        "suggestions",
        {
            "suggestion_id": "sug-valid",
            "user_id": user_id,
            "created_at": near_iso,
            "status": StatusType.SUCCESS.value,
        },
    )
    await repo.save_data(
        "actions",
        {
            "action_id": "act-processing",
            "user_id": user_id,
            "updated_at": near_iso,
            "status": StatusType.PROCESSING.value,
        },
    )
    await repo.save_data(
        "actions",
        {
            "action_id": "act-valid",
            "user_id": user_id,
            "updated_at": near_iso,
            "status": StatusType.SUCCESS.value,
        },
    )

    await repo.save_data(
        "activity_summaries",
        {
            "summary_id": "sum-invalid-status",
            "user_id": user_id,
            "status": None,
            "summary": "exists",
            "period_end": now_iso,
            "created_at": now_iso,
        },
    )
    await repo.save_data(
        "activity_summaries",
        {
            "summary_id": "sum-valid",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "summary": "summary exists",
            "period_end": now_iso,
            "created_at": now_iso,
        },
    )

    await repo.save_data(
        "activity_descriptions",
        {
            "log_id": "ad-old",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "description": "old",
            "period_end": old_iso,
            "created_at": old_iso,
        },
    )
    await repo.save_data(
        "activity_descriptions",
        {
            "log_id": "ad-valid",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "description": "recent",
            "period_end": near_iso,
            "created_at": near_iso,
        },
    )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=user_id,
        suggestion_created_at=now_iso,
        max_parallel_queries=2,
    )

    assert result.error is None
    assert result.data is not None
    slots = {slot["source"]: slot for slot in result.data["slots"]}
    assert slots["long_term_insight"]["status"] == "present"
    assert slots["short_term_insight"]["status"] == "present"
    assert slots["facts"]["status"] == "present"
    assert slots["suggestions"]["status"] == "present"
    assert slots["actions"]["status"] == "present"
    assert slots["activity_summary"]["status"] == "present"
    assert slots["activity_description"]["status"] == "present"


@pytest.mark.asyncio
async def test_memory_source_coverage_snapshot_fails_when_artifact_projection_is_missing() -> (
    None
):
    repo = MockActionAgentRepository()
    user_id = "user-broken-artifact"
    now_iso = datetime.now(UTC).isoformat()

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-facts-broken",
        user_id=user_id,
        source_type="facts",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=user_id,
        suggestion_created_at=now_iso,
        max_parallel_queries=2,
    )

    assert result.data is None
    assert result.error is not None
    assert "facts coverage invariant violated" in result.error
    assert "artifact-facts-broken" in result.error
    assert result.error_kind is RepositoryErrorKind.CONSTRAINT
    assert result.retryable is False


@pytest.mark.asyncio
async def test_memory_source_coverage_snapshot_short_term_insight_missing_when_invalid() -> (
    None
):
    repo = MockActionAgentRepository()
    user_id = "user-short-term-invalid"
    now_iso = datetime.now(UTC).isoformat()

    await repo.save_data(
        "insights",
        {
            "insight_id": "ins-processing",
            "user_id": user_id,
            "status": StatusType.PROCESSING.value,
            "created_at": now_iso,
            "updated_at": now_iso,
            "short_term_insight_data": "has-text",
        },
    )
    await repo.save_data(
        "insights",
        {
            "insight_id": "ins-empty-text",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "created_at": now_iso,
            "updated_at": now_iso,
            "short_term_insight_data": "   ",
        },
    )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=user_id,
        suggestion_created_at=now_iso,
        max_parallel_queries=2,
    )

    assert result.error is None
    assert result.data is not None
    slots = {slot["source"]: slot for slot in result.data["slots"]}
    assert slots["short_term_insight"]["status"] == "missing"


@pytest.mark.asyncio
async def test_memory_source_coverage_snapshot_activity_description_uses_period_end_only() -> (
    None
):
    repo = MockActionAgentRepository()
    user_id = "user-activity-window"
    now = datetime.now(UTC)
    now_iso = now.isoformat()
    near_iso = (now - timedelta(minutes=10)).isoformat()

    await repo.save_data(
        "activity_descriptions",
        {
            "log_id": "ad-updated-only",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "description": "recent-by-updated-at-only",
            "period_end": "",
            "updated_at": near_iso,
            "created_at": near_iso,
        },
    )
    await repo.save_data(
        "activity_descriptions",
        {
            "log_id": "ad-invalid-period-end",
            "user_id": user_id,
            "status": StatusType.SUCCESS.value,
            "description": "invalid-period-end-format",
            "period_end": "not-a-date",
            "updated_at": near_iso,
            "created_at": near_iso,
        },
    )

    result = await repo.get_memory_source_coverage_snapshot(
        user_id=user_id,
        suggestion_created_at=now_iso,
        max_parallel_queries=2,
    )

    assert result.error is None
    assert result.data is not None
    slots = {slot["source"]: slot for slot in result.data["slots"]}
    assert slots["activity_description"]["status"] == "missing"


@pytest.mark.asyncio
async def test_memory_source_coverage_snapshot_marks_unknown_when_anchor_missing() -> (
    None
):
    repo = MockActionAgentRepository()
    result = await repo.get_memory_source_coverage_snapshot(
        user_id="user-1",
        suggestion_created_at=None,
        max_parallel_queries=2,
    )

    assert result.error is None
    assert result.data is not None
    slots = {slot["source"]: slot for slot in result.data["slots"]}
    assert slots["activity_description"]["status"] == "unknown"
