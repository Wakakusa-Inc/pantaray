"""Publication of the Agent Experience category of one unified Memory run."""

from __future__ import annotations

import json
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.schema.agent.base import JSONValue

from .agent_experience_validation import (
    build_agent_experience_evidence_edges,
    validate_agent_experience_publication,
)
from .errors import MemoryCatalogIntegrityError
from .memory_run_binding import (
    MemoryRunBinding,
    memory_run_binding_from_intent,
    memory_run_binding_payload,
    record_memory_run_category,
)
from .models import MemoryDraftCheckpoint, MemoryRevision
from .publication import (
    MemoryPublicationRequest,
    publish_artifact_revision,
)


@dataclass(frozen=True, slots=True)
class AgentExperiencePublication:
    """Agent Experience has no domain table: the artifact tree is the record."""

    binding: MemoryRunBinding
    draft: MemoryDraftCheckpoint

    def __post_init__(self) -> None:
        if self.draft.user_id != self.binding.user_id:
            raise ValueError("Agent Experience draft belongs to another user")


def publish_agent_experience_artifact(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    artifact_root: Path,
    publication: AgentExperiencePublication,
) -> MemoryRevision:
    revision_id = f"rev_{uuid.uuid4().hex}"

    def build_request(connection: sqlite3.Connection) -> MemoryPublicationRequest:
        validate_agent_experience_publication(
            connection=connection,
            publication=publication,
        )
        return MemoryPublicationRequest(
            source="agent_experience",
            source_record_id=publication.binding.user_id,
            draft=publication.draft,
            body_kind="artifact_tree",
            revision_id=revision_id,
            evidence_edges=build_agent_experience_evidence_edges(
                connection=connection,
                draft=publication.draft,
                revision_id=revision_id,
            ),
            intent_kind="agent_experience",
            domain_payload_json=_publication_payload_json(publication),
        )

    return publish_artifact_revision(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
        artifact_root=artifact_root,
        build_request=build_request,
        write_domain_projection=lambda connection, revision: (
            write_agent_experience_projection(
                connection=connection,
                revision=revision,
                publication=publication,
            )
        ),
    )


def write_agent_experience_projection(
    *,
    connection: sqlite3.Connection,
    revision: MemoryRevision,
    publication: AgentExperiencePublication,
) -> None:
    if revision.artifact_root_path is None:
        raise MemoryCatalogIntegrityError("Agent Experience artifact path is absent")
    if publication.draft.owner_node_id != revision.node_id:
        raise MemoryCatalogIntegrityError("Agent Experience node changed")
    validate_agent_experience_publication(
        connection=connection,
        publication=publication,
    )
    record_memory_run_category(
        connection=connection,
        binding=publication.binding,
        source="agent_experience",
        revision=revision,
    )


def agent_experience_publication_from_intent(
    *, payload_json: str, draft: MemoryDraftCheckpoint
) -> AgentExperiencePublication:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise MemoryCatalogIntegrityError(
            "Agent Experience intent payload is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError(
            "Agent Experience intent payload must be an object"
        )
    if set(payload) != {"memory_run"}:
        raise MemoryCatalogIntegrityError(
            "Agent Experience intent payload shape is invalid"
        )
    return AgentExperiencePublication(
        binding=memory_run_binding_from_intent(payload["memory_run"]),
        draft=draft,
    )


def _publication_payload_json(publication: AgentExperiencePublication) -> str:
    payload: dict[str, JSONValue] = {
        "memory_run": memory_run_binding_payload(publication.binding)
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


__all__ = [
    "AgentExperiencePublication",
    "agent_experience_publication_from_intent",
    "publish_agent_experience_artifact",
    "write_agent_experience_projection",
]
