from __future__ import annotations

import sqlite3
from typing import TYPE_CHECKING

from .agent_experience_content import (
    AGENT_EXPERIENCE_INDEX_PATH,
    parse_agent_experience_evidence,
    render_action_evidence_anchor,
)
from .agent_experience_delta import parse_agent_experience_tree
from .errors import MemoryCatalogIntegrityError
from .memory_run_binding import MemoryRunBinding, validate_memory_run_runtime
from .models import DraftLink, MemoryDraftCheckpoint, MemoryEvidenceEdge

if TYPE_CHECKING:
    from .agent_experience import AgentExperiencePublication


def validate_agent_experience_publication(
    *, connection: sqlite3.Connection, publication: AgentExperiencePublication
) -> None:
    parse_agent_experience_tree(publication.draft.documents)
    validate_memory_run_runtime(connection=connection, binding=publication.binding)
    validate_agent_experience_evidence_links(
        connection=connection,
        draft=publication.draft,
        binding=publication.binding,
    )


def build_agent_experience_evidence_edges(
    *,
    connection: sqlite3.Connection,
    draft: MemoryDraftCheckpoint,
    revision_id: str,
) -> tuple[MemoryEvidenceEdge, ...]:
    """Derive the source-Action edges of a tree whose evidence may be empty."""

    target_ids = tuple(
        sorted(
            {link.target_fragment_id for link in draft.links if link.state != "removed"}
        )
    )
    if not target_ids:
        return ()
    placeholders = ",".join("?" for _ in target_ids)
    rows = connection.execute(
        f"""
        SELECT fragments.fragment_id, fragments.revision_id
        FROM memory_fragments AS fragments
        JOIN memory_revisions AS revisions
          ON revisions.user_id = fragments.user_id
         AND revisions.revision_id = fragments.revision_id
        JOIN memory_nodes AS nodes
          ON nodes.user_id = revisions.user_id
         AND nodes.node_id = revisions.node_id
        WHERE fragments.user_id = ? AND fragments.fragment_id IN ({placeholders})
          AND nodes.source_type = 'action'
          AND nodes.lifecycle IN ('active', 'tombstoned')
          AND nodes.integrity = 'healthy' AND revisions.body_kind = 'inline'
        """,
        (draft.user_id, *target_ids),
    ).fetchall()
    if {str(row["fragment_id"]) for row in rows} != set(target_ids):
        raise MemoryCatalogIntegrityError(
            "Agent Experience evidence does not resolve to successful Actions"
        )
    return tuple(
        MemoryEvidenceEdge(
            user_id=draft.user_id,
            derived_revision_id=revision_id,
            source_revision_id=source_revision_id,
            evidence_role="source_action",
        )
        for source_revision_id in sorted({str(row["revision_id"]) for row in rows})
    )


def validate_agent_experience_evidence_links(
    *,
    connection: sqlite3.Connection,
    draft: MemoryDraftCheckpoint,
    binding: MemoryRunBinding | None = None,
) -> None:
    """Every visible evidence tag maps to exactly one link on a real Action.

    ``binding`` narrows the check to the Actions one Memory run owns: an entry
    the run touched may only cite an Action of that run, and it must cite the
    revision that run's terminal published. A repair carries links forward
    without a run and passes no binding.
    """

    parse_agent_experience_tree(draft.documents)
    evidence = tuple(
        (item.local_ref_id, document.source_path, item.action_id)
        for document in draft.documents
        if document.source_path != AGENT_EXPERIENCE_INDEX_PATH
        for item in parse_agent_experience_evidence(document.content)
    )
    evidence_by_ref = {
        local_ref_id: (source_path, action_id)
        for local_ref_id, source_path, action_id in evidence
    }
    active_links = tuple(link for link in draft.links if link.state != "removed")
    links_by_ref = {link.local_ref_id: link for link in active_links}
    if (
        len(evidence_by_ref) != len(evidence)
        or len(links_by_ref) != len(active_links)
        or set(evidence_by_ref) != set(links_by_ref)
    ):
        raise MemoryCatalogIntegrityError(
            "Agent Experience evidence and links are not one-to-one"
        )
    for local_ref_id, (source_path, action_id) in evidence_by_ref.items():
        link = links_by_ref[local_ref_id]
        if (
            link.source_path != source_path
            or link.source_anchor_text != _expected_evidence_anchor(link, action_id)
            or link.source_anchor_occurrence != 1
            or link.reference_note != "source action"
        ):
            raise MemoryCatalogIntegrityError(
                "Agent Experience evidence link metadata is invalid"
            )
        _validate_action_evidence_target(
            connection=connection,
            user_id=draft.user_id,
            action_id=action_id,
            target_fragment_id=link.target_fragment_id,
            required_revision_id=_required_revision_id(
                binding=binding, action_id=action_id, link=link
            ),
        )


def _required_revision_id(
    *, binding: MemoryRunBinding | None, action_id: str, link: DraftLink
) -> str | None:
    if binding is None or link.state == "carried":
        return None
    evidence = binding.evidence_for(action_id)
    if evidence is None:
        raise MemoryCatalogIntegrityError(
            "Agent Experience cites an Action outside its Memory run"
        )
    if evidence.source_action_revision_id is None:
        raise MemoryCatalogIntegrityError(
            "Agent Experience cites an Action turn that published no revision"
        )
    return evidence.source_action_revision_id


def _expected_evidence_anchor(link: DraftLink, action_id: str) -> str:
    anchor = render_action_evidence_anchor(action_id)
    if link.state == "carried":
        return (
            f"{anchor.removeprefix('- ')} "
            f'[[ref:{link.local_ref_id} note:"{link.reference_note}"]]'
        )
    return str(anchor)


def _validate_action_evidence_target(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    target_fragment_id: str,
    required_revision_id: str | None,
) -> None:
    row = connection.execute(
        """
        SELECT 1
        FROM memory_fragments AS fragments
        JOIN memory_revisions AS revisions
          ON revisions.user_id = fragments.user_id
         AND revisions.revision_id = fragments.revision_id
        JOIN memory_nodes AS nodes
          ON nodes.user_id = revisions.user_id
         AND nodes.node_id = revisions.node_id
        WHERE fragments.user_id = ? AND fragments.fragment_id = ?
          AND nodes.source_type = 'action' AND nodes.source_record_id = ?
          AND nodes.lifecycle IN ('active', 'tombstoned')
          AND nodes.integrity = 'healthy' AND revisions.body_kind = 'inline'
          AND (? IS NULL OR revisions.revision_id = ?)
        """,
        (
            user_id,
            target_fragment_id,
            action_id,
            required_revision_id,
            required_revision_id,
        ),
    ).fetchone()
    if row is None:
        raise MemoryCatalogIntegrityError(
            "Agent Experience evidence target is not its displayed Action"
        )


__all__ = [
    "build_agent_experience_evidence_edges",
    "validate_agent_experience_evidence_links",
    "validate_agent_experience_publication",
]
