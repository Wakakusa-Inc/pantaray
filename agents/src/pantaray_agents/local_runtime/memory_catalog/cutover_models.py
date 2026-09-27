from __future__ import annotations

from dataclasses import dataclass

from pantaray_agents.local_runtime.memory_references.reference_parser import (
    MarkdownReferenceOccurrence,
)

from .cutover_records import LegacyMemoryRecord
from .models import MemoryDocument


@dataclass(frozen=True, slots=True)
class PlannedLink:
    local_ref_id: str
    source_path: str
    occurrence: MarkdownReferenceOccurrence
    target: LegacyMemoryRecord
    created_at: str


@dataclass(frozen=True, slots=True)
class QuarantinedLink:
    local_ref_id: str
    source_path: str
    source_markup: str
    target_memory_key: str | None
    reason: str


@dataclass(frozen=True, slots=True)
class PlannedRecord:
    record: LegacyMemoryRecord
    node_id: str
    raw_revision_id: str
    current_revision_id: str
    current_documents: tuple[MemoryDocument, ...]
    raw_artifact_path: str | None
    current_artifact_path: str | None
    links: tuple[PlannedLink, ...]
    quarantine: tuple[QuarantinedLink, ...]
