from __future__ import annotations

import sqlite3
import uuid

from .draft import create_memory_draft
from .models import MemoryDocument, MemoryEvidenceEdge, MemoryRevision, MemorySource
from .publication import MemoryPublicationRequest, publish_inline_revision
from .repository import ensure_preparing_node


def register_inline_domain_memory(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    source: MemorySource,
    source_record_id: str,
    content: str,
) -> MemoryRevision:
    return register_inline_memory_document(
        connection=connection,
        user_id=user_id,
        source=source,
        source_record_id=source_record_id,
        document=MemoryDocument("body.md", content),
    )


def register_inline_memory_document(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    source: MemorySource,
    source_record_id: str,
    document: MemoryDocument,
) -> MemoryRevision:
    connection.row_factory = sqlite3.Row
    node = ensure_preparing_node(
        connection=connection,
        user_id=user_id,
        source=source,
        source_record_id=source_record_id,
    )
    draft = create_memory_draft(
        user_id=user_id,
        owner_node_id=node.node_id,
        base_revision_id=node.current_revision_id,
        documents=(document,),
    )
    return publish_inline_revision(
        connection=connection,
        request=MemoryPublicationRequest(
            source=source,
            source_record_id=source_record_id,
            draft=draft,
            body_kind="inline",
        ),
    )


def register_activity_summary_memory(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    summary_id: str,
    content: str,
    source_ids: tuple[str, ...],
) -> MemoryRevision:
    connection.row_factory = sqlite3.Row
    node = ensure_preparing_node(
        connection=connection,
        user_id=user_id,
        source="activity_summary",
        source_record_id=summary_id,
    )
    revision_id = f"rev_{uuid.uuid4().hex}"
    source_rows = (
        connection.execute(
            f"""
        SELECT current_revision_id
        FROM memory_nodes
        WHERE user_id = ? AND lifecycle = 'active' AND integrity = 'healthy'
          AND source_type IN ('activity_log', 'activity_summary')
          AND source_record_id IN ({", ".join("?" for _ in source_ids)})
        """,
            (user_id, *source_ids),
        ).fetchall()
        if source_ids
        else ()
    )
    source_revisions = tuple(str(row["current_revision_id"]) for row in source_rows)
    if len(source_revisions) != len(set(source_ids)):
        raise ValueError(
            "every activity summary source must have a current catalog revision"
        )
    draft = create_memory_draft(
        user_id=user_id,
        owner_node_id=node.node_id,
        base_revision_id=node.current_revision_id,
        documents=(MemoryDocument("body.md", content),),
    )
    return publish_inline_revision(
        connection=connection,
        request=MemoryPublicationRequest(
            source="activity_summary",
            source_record_id=summary_id,
            draft=draft,
            body_kind="inline",
            revision_id=revision_id,
            evidence_edges=tuple(
                MemoryEvidenceEdge(
                    user_id=user_id,
                    derived_revision_id=revision_id,
                    source_revision_id=source_revision_id,
                    evidence_role="summary_source",
                )
                for source_revision_id in source_revisions
            ),
        ),
    )
