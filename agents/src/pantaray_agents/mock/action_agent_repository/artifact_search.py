from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Literal

from pantaray_agents.local_runtime.memory_references import build_memory_key

from ..mock_action_agent_repository_types import CoverageRow, MemorySearchResultRow
from .memory_search import (
    mock_memory_search_snippet,
    mock_memory_search_text_score,
    mock_time_hint_score,
)

type ArtifactSourceId = Literal["long_term_insight", "facts"]


def search_mock_artifact_source_rows(
    *,
    data: Mapping[str, list[CoverageRow]],
    user_id: str,
    source: ArtifactSourceId,
    query: str,
    keywords: list[str],
    time_hint_center: datetime | None,
    time_hint_radius_hours: int | None,
    limit: int,
) -> list[MemorySearchResultRow]:
    artifact_rows = [
        row
        for row in data.get("memory_artifacts", [])
        if row.get("user_id") == user_id and row.get("source_type") == source
    ]
    artifact_rows.sort(
        key=lambda row: _sortable_value(
            row.get("logical_updated_at") or row.get("logical_created_at")
        ),
        reverse=True,
    )

    results: list[MemorySearchResultRow] = []
    for artifact_row in artifact_rows:
        artifact_id = str(artifact_row.get("artifact_id") or "").strip()
        if not artifact_id:
            continue
        file_rows = [
            row
            for row in data.get("memory_artifact_files", [])
            if row.get("artifact_id") == artifact_id
        ]
        file_rows.sort(
            key=lambda row: _sortable_value(
                row.get("updated_at") or row.get("relative_path")
            )
        )
        file_ids = {
            str(row.get("file_id") or "").strip()
            for row in file_rows
            if str(row.get("file_id") or "").strip()
        }
        if not file_ids:
            continue
        block_rows = [
            row
            for row in data.get("memory_artifact_blocks", [])
            if str(row.get("file_id") or "").strip() in file_ids
        ]
        block_rows.sort(key=lambda row: _block_sort_key(row.get("block_index")))
        file_rows_by_id = {
            str(row.get("file_id") or "").strip(): row
            for row in file_rows
            if str(row.get("file_id") or "").strip()
        }
        for block_row in block_rows:
            content = _select_content(block_row=block_row, keywords=keywords)
            if content is None:
                continue
            file_id = str(block_row.get("file_id") or "").strip()
            file_row = file_rows_by_id.get(file_id)
            if file_row is None:
                continue
            record_id = str(artifact_row.get("source_record_id") or "").strip()
            snippet = mock_memory_search_snippet(text=content, query=query)
            result: MemorySearchResultRow = {
                "source": source,
                "record_id": record_id,
                "created_at": _format_result_timestamp(
                    artifact_row.get("logical_created_at")
                ),
                "updated_at": _format_result_timestamp(
                    artifact_row.get("logical_updated_at")
                ),
                "content": snippet,
                "storage_path": _build_storage_path(
                    root_path=artifact_row.get("root_path"),
                    relative_path=file_row.get("relative_path"),
                ),
                "block_id": str(block_row.get("block_id") or ""),
                "heading_path": str(block_row.get("heading_path") or ""),
                "available_ref_ids": [],
                "score": mock_memory_search_text_score(text=content, query=query)
                + mock_time_hint_score(
                    value=artifact_row.get("logical_updated_at")
                    or artifact_row.get("logical_created_at"),
                    center=time_hint_center,
                    radius_hours=time_hint_radius_hours,
                ),
            }
            memory_key = _build_memory_key(source=source, record_id=record_id)
            if memory_key is not None:
                result["memory_key"] = memory_key
            results.append(result)
    results.sort(
        key=lambda row: (
            float(row.get("score") or 0.0),
            _sortable_value(row.get("updated_at")),
            str(row.get("block_id") or ""),
        ),
        reverse=True,
    )
    deduped = _dedupe_rows_by_record_id(results)
    if limit > 0:
        return deduped[:limit]
    return deduped


def _select_content(
    *,
    block_row: CoverageRow,
    keywords: list[str],
) -> str | None:
    search_text = str(block_row.get("search_text") or "")
    preview_text = str(block_row.get("preview_text") or "")
    haystacks = [text for text in (preview_text, search_text) if text]
    if not haystacks:
        return None
    if not keywords:
        return haystacks[0]
    normalized_keywords = [keyword.casefold() for keyword in keywords]
    for text in haystacks:
        lowered = text.casefold()
        if any(keyword in lowered for keyword in normalized_keywords):
            return text
    return None


def _build_storage_path(*, root_path: object, relative_path: object) -> str:
    root = str(root_path or "").rstrip("/")
    relative = str(relative_path or "").lstrip("/")
    if not root:
        return relative
    if not relative:
        return root
    return f"{root}/{relative}"


def _build_memory_key(*, source: ArtifactSourceId, record_id: str) -> str | None:
    if not record_id:
        return None
    key_source = "fact" if source == "facts" else source
    return build_memory_key(source=key_source, record_id=record_id)


def _block_sort_key(value: object) -> tuple[int, str]:
    if isinstance(value, int):
        return value, ""
    if isinstance(value, str):
        try:
            return int(value), value
        except ValueError:
            return 0, value
    return 0, ""


def _sortable_value(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _format_result_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value or "")


def _dedupe_rows_by_record_id(
    rows: list[MemorySearchResultRow],
) -> list[MemorySearchResultRow]:
    deduped: list[MemorySearchResultRow] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        key = (str(row.get("source") or ""), str(row.get("record_id") or ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(row)
    return deduped
