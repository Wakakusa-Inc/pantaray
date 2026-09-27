from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.local_runtime.memory_references.reference_parser import (
    extract_markdown_references,
)

from .artifact_workspace import read_artifact_revision_documents
from .errors import MemoryCatalogIntegrityError
from .fragments import artifact_content_sha256
from .models import DraftLink, MemoryDocument
from .repository import (
    list_revision_fragments,
    list_revision_links,
    load_revision,
)

REVISION_INTEGRITY_ERRORS = (
    MemoryCatalogIntegrityError,
    UnicodeError,
    FileNotFoundError,
    NotADirectoryError,
    IsADirectoryError,
)


@dataclass(frozen=True, slots=True)
class RevisionInspection:
    documents: tuple[MemoryDocument, ...]
    carried_links: tuple[DraftLink, ...]
    invalid_anchors: tuple[tuple[str, int], ...]
    has_orphan_links: bool

    @property
    def needs_link_repair(self) -> bool:
        return bool(self.invalid_anchors or self.has_orphan_links)


def inspect_revision(
    *,
    connection: sqlite3.Connection,
    artifact_root: Path,
    user_id: str,
    revision_id: str,
) -> RevisionInspection:
    revision = load_revision(
        connection=connection, user_id=user_id, revision_id=revision_id
    )
    if revision is None:
        raise MemoryCatalogIntegrityError("memory revision is absent")
    fragments = {
        item.fragment_id: item
        for item in list_revision_fragments(
            connection=connection, user_id=user_id, revision_id=revision_id
        )
    }
    if revision.body_kind == "artifact_tree":
        documents = read_artifact_revision_documents(
            connection=connection,
            artifact_root=artifact_root,
            user_id=user_id,
            revision_id=revision_id,
        )
    else:
        if revision.inline_body is None:
            raise MemoryCatalogIntegrityError("inline revision body is absent")
        roots = [f for f in fragments.values() if f.block_kind == "document_root"]
        if len(roots) != 1:
            raise MemoryCatalogIntegrityError("inline document is absent or ambiguous")
        documents = (MemoryDocument(roots[0].source_path, revision.inline_body),)
        if artifact_content_sha256(documents) != revision.content_sha256:
            raise MemoryCatalogIntegrityError("inline revision hash changed")
    links = {
        item.local_ref_id: item
        for item in list_revision_links(
            connection=connection, user_id=user_id, revision_id=revision_id
        )
    }
    occurrences = [
        (document.source_path, occurrence)
        for document in documents
        for occurrence in extract_markdown_references(document.content)
    ]
    counts: dict[str, int] = {}
    for _, occurrence in occurrences:
        counts[occurrence.local_ref_id] = counts.get(occurrence.local_ref_id, 0) + 1
    valid_ids: set[str] = set()
    invalid_anchors: list[tuple[str, int]] = []
    carried: list[DraftLink] = []
    for source_path, occurrence in occurrences:
        link = links.get(occurrence.local_ref_id)
        if link is None:
            invalid_anchors.append((source_path, occurrence.anchor_order))
            continue
        source_fragment = fragments.get(link.source_fragment_id)
        target_exists = connection.execute(
            "SELECT 1 FROM memory_fragments WHERE user_id = ? AND fragment_id = ?",
            (user_id, link.target_fragment_id),
        ).fetchone()
        if not (
            counts[occurrence.local_ref_id] == 1
            and source_fragment is not None
            and source_fragment.source_path == source_path
            and occurrence.note == link.reference_note
            and target_exists is not None
        ):
            invalid_anchors.append((source_path, occurrence.anchor_order))
            continue
        assert source_fragment is not None
        valid_ids.add(link.local_ref_id)
        carried.append(
            DraftLink(
                local_ref_id=link.local_ref_id,
                target_fragment_id=link.target_fragment_id,
                source_path=source_path,
                source_anchor_text=source_fragment.content_text,
                source_anchor_occurrence=1,
                reference_note=link.reference_note,
                created_at=link.created_at,
                state="carried",
            )
        )
    return RevisionInspection(
        documents=documents,
        carried_links=tuple(carried),
        invalid_anchors=tuple(invalid_anchors),
        has_orphan_links=set(links) != valid_ids,
    )


__all__ = [
    "REVISION_INTEGRITY_ERRORS",
    "RevisionInspection",
    "inspect_revision",
]
