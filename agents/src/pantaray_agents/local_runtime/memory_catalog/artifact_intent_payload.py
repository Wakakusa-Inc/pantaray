from __future__ import annotations

import json

from pydantic import BaseModel, ConfigDict, ValidationError

from pantaray_agents.schema.agent.action import MemoryDraftCheckpointModel

from .checkpoint import deserialize_memory_draft, serialize_memory_draft
from .errors import MemoryCatalogError, MemoryCatalogIntegrityError
from .models import MemoryDraftCheckpoint


class _ArtifactIntentPayloadEnvelope(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    domain_payload_json: str
    draft_checkpoint: MemoryDraftCheckpointModel


def encode_artifact_intent_payload(
    *, domain_payload_json: str, draft: MemoryDraftCheckpoint
) -> str:
    _validate_domain_payload(domain_payload_json)
    envelope = _ArtifactIntentPayloadEnvelope(
        domain_payload_json=domain_payload_json,
        draft_checkpoint=serialize_memory_draft(draft),
    )
    return json.dumps(
        envelope.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def decode_artifact_intent_payload(
    *,
    payload_json: str,
    expected_user_id: str,
    expected_node_id: str,
    expected_base_revision_id: str | None,
) -> tuple[str, MemoryDraftCheckpoint]:
    try:
        envelope = _ArtifactIntentPayloadEnvelope.model_validate_json(payload_json)
    except ValidationError as exc:
        raise MemoryCatalogIntegrityError(
            "artifact intent payload envelope is invalid"
        ) from exc
    _validate_domain_payload(envelope.domain_payload_json)
    try:
        draft = deserialize_memory_draft(envelope.draft_checkpoint)
    except (MemoryCatalogError, ValueError) as exc:
        raise MemoryCatalogIntegrityError(
            "artifact intent draft checkpoint is invalid"
        ) from exc
    if (
        draft.user_id != expected_user_id
        or draft.owner_node_id != expected_node_id
        or draft.base_revision_id != expected_base_revision_id
    ):
        raise MemoryCatalogIntegrityError(
            "artifact intent draft identity does not match intent"
        )
    return envelope.domain_payload_json, draft


def _validate_domain_payload(payload_json: str) -> None:
    try:
        payload = json.loads(payload_json)
    except json.JSONDecodeError as exc:
        raise MemoryCatalogIntegrityError(
            "artifact intent domain payload is invalid"
        ) from exc
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError(
            "artifact intent domain payload must be an object"
        )
