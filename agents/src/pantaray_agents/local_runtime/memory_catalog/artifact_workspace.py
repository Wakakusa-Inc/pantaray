from __future__ import annotations

import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.memory_references.reference_parser import (
    extract_markdown_references,
    remove_reference_ids,
)

from .agent_experience_content import (
    AGENT_EXPERIENCE_ENTRIES_ROOT,
    is_action_evidence_line,
)
from .draft import create_memory_draft
from .errors import MemoryCatalogIntegrityError
from .fragments import artifact_content_sha256
from .models import DraftLink, MemoryDocument, MemoryDraftCheckpoint, MemorySource
from .repository import (
    ensure_preparing_node,
    list_revision_fragments,
    list_revision_links,
    load_node_by_source,
    load_revision,
)


def prepare_artifact_draft(
    *,
    connection: sqlite3.Connection,
    artifact_root: Path,
    user_id: str,
    source: MemorySource,
    source_record_id: str,
    initial_documents: tuple[MemoryDocument, ...],
) -> MemoryDraftCheckpoint:
    node = load_node_by_source(
        connection=connection,
        user_id=user_id,
        source=source,
        source_record_id=source_record_id,
    )
    if node is None:
        node = ensure_preparing_node(
            connection=connection,
            user_id=user_id,
            source=source,
            source_record_id=source_record_id,
        )
    if node.lifecycle == "preparing":
        if node.current_revision_id is not None:
            raise MemoryCatalogIntegrityError("preparing node has a current revision")
        documents = initial_documents
        carried_links: tuple[DraftLink, ...] = ()
    else:
        if node.current_revision_id is None:
            raise MemoryCatalogIntegrityError("active memory node has no revision")
        links = list_revision_links(
            connection=connection,
            user_id=user_id,
            revision_id=node.current_revision_id,
        )
        documents = drop_deleted_references(
            read_artifact_revision_documents(
                connection=connection,
                artifact_root=artifact_root,
                user_id=user_id,
                revision_id=node.current_revision_id,
            ),
            linked_ref_ids=frozenset(link.local_ref_id for link in links),
        )
        carried_links = _load_carried_links(
            connection=connection,
            user_id=user_id,
            revision_id=node.current_revision_id,
            documents=documents,
        )
    return create_memory_draft(
        user_id=user_id,
        owner_node_id=node.node_id,
        base_revision_id=node.current_revision_id,
        documents=documents,
        carried_links=carried_links,
    )


def read_artifact_revision_documents(
    *,
    connection: sqlite3.Connection,
    artifact_root: Path,
    user_id: str,
    revision_id: str,
) -> tuple[MemoryDocument, ...]:
    revision = load_revision(
        connection=connection,
        user_id=user_id,
        revision_id=revision_id,
    )
    if revision is None or revision.body_kind != "artifact_tree":
        raise MemoryCatalogIntegrityError("artifact memory revision is absent")
    if revision.artifact_root_path is None:
        raise MemoryCatalogIntegrityError("artifact revision path is absent")
    root = _confined_path(artifact_root, revision.artifact_root_path)
    document_paths = tuple(
        sorted(
            {
                fragment.source_path
                for fragment in list_revision_fragments(
                    connection=connection,
                    user_id=user_id,
                    revision_id=revision_id,
                )
                if fragment.block_kind == "document_root"
            }
        )
    )
    documents = tuple(
        MemoryDocument(path, _confined_path(root, path).read_text(encoding="utf-8"))
        for path in document_paths
    )
    if not documents or artifact_content_sha256(documents) != revision.content_sha256:
        raise MemoryCatalogIntegrityError(
            "artifact revision content is missing or changed"
        )
    return documents


def drop_deleted_references(
    documents: tuple[MemoryDocument, ...], *, linked_ref_ids: frozenset[str]
) -> tuple[MemoryDocument, ...]:
    """Drop tags whose link went with a deleted conversation (evidence: the line)."""

    return tuple(
        MemoryDocument(
            document.source_path,
            _drop_unlinked_tags(
                document.content,
                linked_ref_ids=linked_ref_ids,
                is_experience_entry=document.source_path.startswith(
                    f"{AGENT_EXPERIENCE_ENTRIES_ROOT}/"
                ),
            ),
        )
        for document in documents
    )


def _drop_unlinked_tags(
    content: str, *, linked_ref_ids: frozenset[str], is_experience_entry: bool
) -> str:
    lines: list[str] = []
    for line in content.splitlines(keepends=True):
        unlinked = {
            occurrence.local_ref_id for occurrence in extract_markdown_references(line)
        } - linked_ref_ids
        if not unlinked:
            lines.append(line)
        elif not (is_experience_entry and is_action_evidence_line(line)):
            lines.append(remove_reference_ids(line, unlinked))
    return "".join(lines)


def _load_carried_links(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    revision_id: str,
    documents: tuple[MemoryDocument, ...],
) -> tuple[DraftLink, ...]:
    links = list_revision_links(
        connection=connection,
        user_id=user_id,
        revision_id=revision_id,
    )
    source_by_fragment = {
        fragment.fragment_id: fragment
        for fragment in list_revision_fragments(
            connection=connection,
            user_id=user_id,
            revision_id=revision_id,
        )
    }
    occurrences = {
        occurrence.local_ref_id: (document.source_path, occurrence)
        for document in documents
        for occurrence in extract_markdown_references(document.content)
    }
    carried: list[DraftLink] = []
    for link in links:
        source_fragment = source_by_fragment.get(link.source_fragment_id)
        occurrence_entry = occurrences.get(link.local_ref_id)
        if source_fragment is None or occurrence_entry is None:
            raise MemoryCatalogIntegrityError(
                "base revision link manifest is inconsistent"
            )
        source_path, occurrence = occurrence_entry
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
    return tuple(carried)


def _confined_path(root: Path, relative_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (root / relative_path).resolve()
    if candidate != resolved_root and resolved_root not in candidate.parents:
        raise MemoryCatalogIntegrityError("artifact path escapes its root")
    return candidate
