"""memory_search の record payload builder。"""

from __future__ import annotations

from pantaray_agents.schema.repositories.repository import DBRow


def build_memory_record_payload(
    *,
    source: str,
    record_id: str,
    created_at: str,
    updated_at: str,
    content: str,
    memory_key: str | None = None,
    available_ref_ids: list[str] | None = None,
) -> DBRow:
    row: DBRow = {
        "source": source,
        "record_id": record_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "content": content,
    }
    if memory_key is not None:
        row["memory_key"] = memory_key
    if available_ref_ids is not None:
        row["available_ref_ids"] = available_ref_ids
    return row


def build_activity_description_payload(
    *,
    record_id: str,
    created_at: str,
    updated_at: str,
    content: str,
    period_start: str,
    period_end: str,
    memory_key: str | None = None,
    available_ref_ids: list[str] | None = None,
) -> DBRow:
    row = build_memory_record_payload(
        source="activity_description",
        record_id=record_id,
        created_at=created_at,
        updated_at=updated_at,
        content=content,
        memory_key=memory_key,
        available_ref_ids=available_ref_ids,
    )
    row["period_start"] = period_start
    row["period_end"] = period_end
    return row


def build_activity_summary_payload(
    *,
    record_id: str,
    created_at: str,
    updated_at: str,
    content: str,
    summary_type: str,
    period_start: str,
    period_end: str,
    memory_key: str | None = None,
    available_ref_ids: list[str] | None = None,
) -> DBRow:
    row = build_memory_record_payload(
        source="activity_summary",
        record_id=record_id,
        created_at=created_at,
        updated_at=updated_at,
        content=content,
        memory_key=memory_key,
        available_ref_ids=available_ref_ids,
    )
    row["summary_type"] = summary_type
    row["period_start"] = period_start
    row["period_end"] = period_end
    return row


__all__ = [
    "build_activity_description_payload",
    "build_activity_summary_payload",
    "build_memory_record_payload",
]
