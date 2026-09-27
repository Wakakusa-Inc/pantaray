from __future__ import annotations

import sqlite3
from dataclasses import dataclass, replace

from .epoch import build_memory_context_epoch
from .errors import MemoryCatalogIntegrityError
from .models import MemoryContextEpoch, MemoryFragment, MemoryNode, MemorySource
from .repository import list_revision_fragments, load_node_by_source, load_revision


@dataclass(frozen=True, slots=True)
class VisibleMemoryRecord:
    source: MemorySource
    source_record_id: str
    label: str
    revision_id: str | None = None


def build_record_context_epoch(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    run_id: str,
    records: tuple[VisibleMemoryRecord, ...],
) -> MemoryContextEpoch:
    visible: list[tuple[MemoryNode, MemoryFragment, str]] = []
    seen: set[tuple[str, str]] = set()
    for record in records:
        identity = (record.source, record.source_record_id)
        if identity in seen:
            continue
        seen.add(identity)
        node = load_node_by_source(
            connection=connection,
            user_id=user_id,
            source=record.source,
            source_record_id=record.source_record_id,
        )
        if (
            node is None
            or node.lifecycle != "active"
            or node.integrity != "healthy"
            or node.current_revision_id is None
        ):
            raise MemoryCatalogIntegrityError(
                f"visible {record.source} memory is not active in the catalog"
            )
        selected_revision_id = record.revision_id or node.current_revision_id
        revision = load_revision(
            connection=connection,
            user_id=user_id,
            revision_id=selected_revision_id,
        )
        if revision is None or revision.node_id != node.node_id:
            raise MemoryCatalogIntegrityError(
                f"visible {record.source} revision does not belong to its record"
            )
        fragments = list_revision_fragments(
            connection=connection,
            user_id=user_id,
            revision_id=selected_revision_id,
        )
        linkable = tuple(
            fragment
            for fragment in fragments
            if fragment.block_kind not in {"record_root", "document_root"}
        ) or tuple(
            fragment for fragment in fragments if fragment.block_kind == "document_root"
        )
        if not linkable:
            raise MemoryCatalogIntegrityError(
                "visible memory has no linkable fragments"
            )
        visible_node = replace(node, current_revision_id=selected_revision_id)
        visible.extend((visible_node, fragment, record.label) for fragment in linkable)
    return build_memory_context_epoch(
        run_id=run_id,
        user_id=user_id,
        visible=tuple(visible),
    )


def render_context_epoch(epoch: MemoryContextEpoch) -> str:
    if not epoch.items:
        return "N/A"
    blocks = []
    for resolved in epoch.items:
        item = resolved.item
        heading = f" heading={item.heading_path}" if item.heading_path else ""
        blocks.append(
            f"[{item.context_handle}] source={item.source} label={item.label} "
            f"path={item.source_path}{heading}\n{item.content}"
        )
    return "\n\n".join(blocks)
