from __future__ import annotations

import pytest

from .shared import UTC, MockActionAgentRepository, datetime


async def _save_memory_artifact(
    repo: MockActionAgentRepository,
    *,
    artifact_id: str,
    user_id: str,
    source_type: str,
    source_record_id: str,
    logical_created_at: str,
    logical_updated_at: str,
) -> None:
    await repo.save_data(
        "memory_artifacts",
        {
            "artifact_id": artifact_id,
            "user_id": user_id,
            "source_type": source_type,
            "source_record_id": source_record_id,
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
    search_text: str,
    preview_text: str,
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
            "search_text": search_text,
            "preview_text": preview_text,
        },
    )


@pytest.mark.asyncio
async def test_memory_search_long_term_insight_uses_artifact_rows_not_legacy_insights() -> (
    None
):
    repo = MockActionAgentRepository()
    user_id = "user-artifact-long"
    now_iso = datetime.now(UTC).isoformat()

    await repo.save_data(
        "insights",
        {
            "insight_id": "legacy-insight",
            "user_id": user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "long_term_insight_data": "legacy long term insight text",
        },
    )
    await _save_memory_artifact(
        repo,
        artifact_id="artifact-long-1",
        user_id=user_id,
        source_type="long_term_insight",
        source_record_id="insight-artifact-1",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-long-1",
        file_id="artifact-long-file-1",
        block_id="artifact-long-block-1",
        updated_at=now_iso,
        search_text="artifact backed long term insight body",
        preview_text="artifact backed long term insight body",
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="artifact backed long term",
        focus="stable_knowledge",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert len(result.data) == 1
    row = result.data[0]
    assert row["record_id"] == "insight-artifact-1"
    assert row["content"] == "artifact backed long term insight body"
    assert row["storage_path"] == "artifacts/long_term_insight/artifact-long-1/index.md"


@pytest.mark.asyncio
async def test_memory_search_facts_uses_artifact_blocks_for_keyword_search() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-artifact-facts"
    now_iso = datetime.now(UTC).isoformat()

    await repo.save_data(
        "facts",
        {
            "fact_id": "legacy-fact",
            "user_id": user_id,
            "created_at": now_iso,
            "updated_at": now_iso,
            "structured_data": "legacy facts text without the target keyword",
        },
    )
    await _save_memory_artifact(
        repo,
        artifact_id="artifact-fact-1",
        user_id=user_id,
        source_type="facts",
        source_record_id="fact-artifact-1",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-fact-1",
        file_id="artifact-fact-file-1",
        block_id="artifact-fact-block-1",
        updated_at=now_iso,
        search_text="artifact keyword only appears in this block",
        preview_text="artifact keyword only appears in this block",
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="artifact",
        focus="stable_knowledge",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert len(result.data) == 1
    row = result.data[0]
    assert row["record_id"] == "fact-artifact-1"
    assert row["content"] == "artifact keyword only appears in this block"
    assert row["block_id"] == "artifact-fact-block-1"


@pytest.mark.asyncio
async def test_memory_search_artifact_keyword_search_is_case_insensitive() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-artifact-casefold"
    now_iso = datetime.now(UTC).isoformat()

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-case-1",
        user_id=user_id,
        source_type="facts",
        source_record_id="fact-case-1",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-case-1",
        file_id="artifact-case-file-1",
        block_id="artifact-case-block-1",
        updated_at=now_iso,
        search_text="docker isolation appears in lowercase here",
        preview_text="docker isolation appears in lowercase here",
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="Docker",
        focus="stable_knowledge",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert [row["record_id"] for row in result.data] == ["fact-case-1"]


@pytest.mark.asyncio
async def test_memory_search_artifact_dedupes_after_score_sorting() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-artifact-dedupe"
    now_iso = datetime.now(UTC).isoformat()

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-dedupe-1",
        user_id=user_id,
        source_type="facts",
        source_record_id="fact-dedupe-1",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-dedupe-1",
        file_id="artifact-dedupe-file-1",
        block_id="artifact-dedupe-low",
        updated_at=now_iso,
        search_text="Xcode unrelated artifact block",
        preview_text="Xcode unrelated artifact block",
    )
    await repo.save_data(
        "memory_artifact_blocks",
        {
            "block_id": "artifact-dedupe-high",
            "file_id": "artifact-dedupe-file-1",
            "block_kind": "paragraph",
            "heading_path": "Root",
            "block_index": 1,
            "search_text": "Xcode エラー原因 exact phrase artifact block",
            "preview_text": "Xcode エラー原因 exact phrase artifact block",
        },
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="Xcode エラー原因",
        focus="stable_knowledge",
        limit=1,
    )

    assert result.error is None
    assert result.data is not None
    assert result.data[0]["block_id"] == "artifact-dedupe-high"


@pytest.mark.asyncio
async def test_memory_search_artifact_timestamps_are_serialized() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-artifact-timestamps"
    now = datetime.now(UTC)

    await repo.save_data(
        "memory_artifacts",
        {
            "artifact_id": "artifact-timestamps-1",
            "user_id": user_id,
            "source_type": "facts",
            "source_record_id": "fact-timestamps-1",
            "root_path": "artifacts/facts/artifact-timestamps-1",
            "content_sha256": "sha-artifact-timestamps-1",
            "logical_created_at": now,
            "logical_updated_at": now,
            "indexed_at": now,
        },
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-timestamps-1",
        file_id="artifact-timestamps-file-1",
        block_id="artifact-timestamps-block-1",
        updated_at=now.isoformat(),
        search_text="timestamp serialization block",
        preview_text="timestamp serialization block",
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="timestamp",
        focus="stable_knowledge",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert len(result.data) == 1
    assert result.data[0]["created_at"] == now.isoformat()
    assert result.data[0]["updated_at"] == now.isoformat()


@pytest.mark.asyncio
async def test_memory_search_artifact_returns_snippet_like_production() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-artifact-snippet"
    now_iso = datetime.now(UTC).isoformat()
    full_text = f"{'a' * 700} Needle artifact snippet {'b' * 700}"

    await _save_memory_artifact(
        repo,
        artifact_id="artifact-snippet-1",
        user_id=user_id,
        source_type="facts",
        source_record_id="fact-snippet-1",
        logical_created_at=now_iso,
        logical_updated_at=now_iso,
    )
    await _save_memory_artifact_projection(
        repo,
        artifact_id="artifact-snippet-1",
        file_id="artifact-snippet-file-1",
        block_id="artifact-snippet-block-1",
        updated_at=now_iso,
        search_text=full_text,
        preview_text=full_text,
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="Needle",
        focus="stable_knowledge",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert len(result.data[0]["content"]) < len(full_text)
    assert result.data[0]["content"].startswith("...")
    assert result.data[0]["content"].endswith("...")


@pytest.mark.asyncio
async def test_memory_search_activity_focus_reads_activity_description_rows() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-activity-description"
    now_iso = datetime.now(UTC).isoformat()

    await repo.save_data(
        "activity_descriptions",
        {
            "log_id": "activity-log-1",
            "user_id": user_id,
            "description": "Needle activity description body",
            "status": "success",
            "period_start": "2026-03-24T00:00:00Z",
            "period_end": "2026-03-24T00:10:00Z",
            "created_at": now_iso,
            "updated_at": now_iso,
        },
    )

    result = await repo.memory_search(
        user_id=user_id,
        query="Needle activity",
        focus="activity",
        limit=5,
    )

    assert result.error is None
    assert result.data is not None
    assert [row["record_id"] for row in result.data] == ["activity-log-1"]
    row = result.data[0]
    assert row["source"] == "activity_description"
    assert row["memory_key"] == "activity_log:activity-log-1"


@pytest.mark.asyncio
async def test_memory_search_applies_production_status_filters() -> None:
    repo = MockActionAgentRepository()
    user_id = "user-status-filters"
    now_iso = datetime.now(UTC).isoformat()

    for suggestion_id, status in (
        ("sug-success", "success"),
        ("sug-error", "error"),
        ("sug-processing", "processing"),
    ):
        await repo.save_data(
            "suggestions",
            {
                "suggestion_id": suggestion_id,
                "user_id": user_id,
                "status": status,
                "answer": f"Needle status suggestion {suggestion_id}",
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
    for action_id, status in (
        ("act-success", "success"),
        ("act-processing", "processing"),
    ):
        await repo.save_data(
            "actions",
            {
                "action_id": action_id,
                "user_id": user_id,
                "status": status,
                "final_output": f"Needle status action {action_id}",
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )
    for insight_id, status in (
        ("ins-success", "success"),
        ("ins-error", "error"),
    ):
        await repo.save_data(
            "insights",
            {
                "insight_id": insight_id,
                "user_id": user_id,
                "status": status,
                "short_term_insight_data": f"Needle status insight {insight_id}",
                "created_at": now_iso,
                "updated_at": now_iso,
            },
        )

    result = await repo.memory_search(
        user_id=user_id,
        query="Needle status",
        focus="all",
        limit=20,
    )

    assert result.error is None
    assert result.data is not None
    records = {(str(row["source"]), str(row["record_id"])) for row in result.data}
    assert {
        ("suggestions", "sug-success"),
        ("suggestions", "sug-error"),
        ("actions", "act-success"),
        ("short_term_insight", "ins-success"),
    }.issubset(records)
    assert ("suggestions", "sug-processing") not in records
    assert ("actions", "act-processing") not in records
    assert ("short_term_insight", "ins-error") not in records


@pytest.mark.asyncio
async def test_memory_search_rejects_bool_limit() -> None:
    repo = MockActionAgentRepository()

    result = await repo.memory_search(
        user_id="user-bool-limit",
        query="Needle",
        limit=True,
    )

    assert result.error == "memory_search: limit must be a positive integer."


@pytest.mark.asyncio
async def test_memory_search_rejects_bool_time_hint_radius() -> None:
    repo = MockActionAgentRepository()

    result = await repo.memory_search(
        user_id="user-bool-radius",
        query="Needle",
        time_hint={"center": "2026-03-24T00:00:00Z", "radius_hours": True},
    )

    assert (
        result.error
        == "memory_search: time_hint.radius_hours must be a positive integer."
    )
