from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
from typing import TypedDict, cast

from .errors import MemoryArtifactTreeIncompleteError, MemoryCatalogIntegrityError
from .fragments import MEMORY_FRAGMENT_SCHEMA_VERSION, artifact_content_sha256
from .models import (
    DraftLink,
    DraftLinkState,
    MemoryDocument,
    MemoryDraftCheckpoint,
    MemoryIntentKind,
    MemorySource,
)


class ManifestFile(TypedDict):
    path: str
    sha256: str
    byte_size: int


class ManifestLink(TypedDict):
    local_ref_id: str
    target_fragment_id: str
    source_path: str
    source_anchor_text: str
    source_anchor_occurrence: int
    reference_note: str
    created_at: str
    state: str


class ArtifactRevisionManifest(TypedDict):
    revision_id: str
    user_id: str
    node_id: str
    source: str
    source_record_id: str
    base_revision_id: str | None
    draft_session_id: str
    draft_revision: str
    fragment_schema_version: int
    content_sha256: str
    files: list[ManifestFile]
    links: list[ManifestLink]


def build_artifact_manifest(
    *,
    revision_id: str,
    source: MemorySource,
    source_record_id: str,
    draft: MemoryDraftCheckpoint,
) -> str:
    payload: ArtifactRevisionManifest = {
        "revision_id": revision_id,
        "user_id": draft.user_id,
        "node_id": draft.owner_node_id,
        "source": source,
        "source_record_id": source_record_id,
        "base_revision_id": draft.base_revision_id,
        "draft_session_id": draft.draft_session_id,
        "draft_revision": draft.draft_revision,
        "fragment_schema_version": MEMORY_FRAGMENT_SCHEMA_VERSION,
        "content_sha256": artifact_content_sha256(draft.documents),
        "files": [
            {
                "path": item.source_path,
                "sha256": _text_sha256(item.content),
                "byte_size": len(item.content.encode("utf-8")),
            }
            for item in sorted(draft.documents, key=lambda value: value.source_path)
        ],
        "links": [
            {
                "local_ref_id": item.local_ref_id,
                "target_fragment_id": item.target_fragment_id,
                "source_path": item.source_path,
                "source_anchor_text": item.source_anchor_text,
                "source_anchor_occurrence": item.source_anchor_occurrence,
                "reference_note": item.reference_note,
                "created_at": item.created_at,
                "state": item.state,
            }
            for item in draft.links
        ],
    }
    return json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )


def load_artifact_manifest(
    *,
    revision_root: Path,
    expected_manifest_sha256: str,
    expected_revision_id: str,
    expected_user_id: str,
    expected_node_id: str,
) -> ArtifactRevisionManifest:
    try:
        manifest_path = _confined_file(revision_root, "manifest.json")
        raw = manifest_path.read_text(encoding="utf-8")
    except MemoryArtifactTreeIncompleteError as exc:
        raise MemoryCatalogIntegrityError("artifact manifest file is absent") from exc
    if _text_sha256(raw) != expected_manifest_sha256:
        raise MemoryCatalogIntegrityError(
            "artifact manifest hash does not match intent"
        )
    parsed = json.loads(raw)
    if not isinstance(parsed, dict):
        raise MemoryCatalogIntegrityError("artifact manifest must be an object")
    manifest = cast(ArtifactRevisionManifest, parsed)
    if (
        manifest.get("revision_id") != expected_revision_id
        or manifest.get("user_id") != expected_user_id
        or manifest.get("node_id") != expected_node_id
        or manifest.get("fragment_schema_version") != MEMORY_FRAGMENT_SCHEMA_VERSION
    ):
        raise MemoryCatalogIntegrityError(
            "artifact manifest identity does not match intent"
        )
    return manifest


def reconstruct_artifact_draft(
    *, revision_root: Path, manifest: ArtifactRevisionManifest
) -> tuple[MemorySource, str, MemoryDraftCheckpoint]:
    documents = tuple(
        _load_manifest_document(revision_root=revision_root, entry=entry)
        for entry in _require_list(manifest, "files")
    )
    if not documents or artifact_content_sha256(documents) != _require_str(
        manifest, "content_sha256"
    ):
        raise MemoryCatalogIntegrityError("artifact body hash does not match manifest")
    links = tuple(
        _load_manifest_link(entry) for entry in _require_list(manifest, "links")
    )
    source = _require_str(manifest, "source")
    if source not in {
        "activity_log",
        "activity_summary",
        "suggestion",
        "action",
        "agent_experience",
        "short_term_insight",
        "long_term_insight",
        "fact",
    }:
        raise MemoryCatalogIntegrityError("artifact manifest source is invalid")
    draft = MemoryDraftCheckpoint(
        draft_session_id=_require_str(manifest, "draft_session_id"),
        user_id=_require_str(manifest, "user_id"),
        owner_node_id=_require_str(manifest, "node_id"),
        base_revision_id=_optional_str(manifest, "base_revision_id"),
        draft_revision=_require_str(manifest, "draft_revision"),
        documents=documents,
        links=links,
        applied_commands=(),
    )
    return cast(MemorySource, source), _require_str(manifest, "source_record_id"), draft


def manifest_sha256(manifest: str) -> str:
    return _text_sha256(manifest)


def validate_intent_kind(value: str) -> MemoryIntentKind:
    if value not in {
        "fact",
        "long_term_insight",
        "agent_experience",
        "fact_repair",
        "long_term_insight_repair",
        "agent_experience_repair",
    }:
        raise MemoryCatalogIntegrityError("artifact intent kind is invalid")
    return cast(MemoryIntentKind, value)


def _load_manifest_document(*, revision_root: Path, entry: object) -> MemoryDocument:
    if not isinstance(entry, dict):
        raise MemoryCatalogIntegrityError("artifact file descriptor is invalid")
    path = _require_str(entry, "path")
    content = _confined_file(revision_root, path).read_text(encoding="utf-8")
    if len(content.encode("utf-8")) != _require_int(entry, "byte_size") or _text_sha256(
        content
    ) != _require_str(entry, "sha256"):
        raise MemoryCatalogIntegrityError("artifact file does not match manifest")
    return MemoryDocument(path, content)


def _load_manifest_link(entry: object) -> DraftLink:
    if not isinstance(entry, dict):
        raise MemoryCatalogIntegrityError("artifact link descriptor is invalid")
    state = _require_str(entry, "state")
    if state not in {"carried", "pending", "removed"}:
        raise MemoryCatalogIntegrityError("artifact link state is invalid")
    return DraftLink(
        local_ref_id=_require_str(entry, "local_ref_id"),
        target_fragment_id=_require_str(entry, "target_fragment_id"),
        source_path=_require_str(entry, "source_path"),
        source_anchor_text=_require_str(entry, "source_anchor_text"),
        source_anchor_occurrence=_require_int(entry, "source_anchor_occurrence"),
        reference_note=_require_str(entry, "reference_note"),
        created_at=_require_str(entry, "created_at"),
        state=cast(DraftLinkState, state),
    )


def _confined_file(root: Path, relative_path: str) -> Path:
    pure = PurePosixPath(relative_path)
    if pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise MemoryCatalogIntegrityError("artifact manifest path is invalid")
    unresolved_candidate = root.joinpath(*pure.parts)
    if unresolved_candidate.is_symlink():
        raise MemoryCatalogIntegrityError("artifact manifest file is unsafe")
    candidate = unresolved_candidate.resolve()
    resolved_root = root.resolve()
    if resolved_root not in candidate.parents:
        raise MemoryCatalogIntegrityError(
            "artifact manifest path escapes revision root"
        )
    if not candidate.exists():
        raise MemoryArtifactTreeIncompleteError("artifact manifest file is absent")
    if not candidate.is_file():
        raise MemoryCatalogIntegrityError("artifact manifest file is unsafe")
    return candidate


def _text_sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _require_str(payload: object, key: str) -> str:
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError("artifact manifest object is invalid")
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise MemoryCatalogIntegrityError(f"artifact manifest {key} is invalid")
    return value


def _optional_str(payload: object, key: str) -> str | None:
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError("artifact manifest object is invalid")
    value = payload.get(key)
    if value is not None and not isinstance(value, str):
        raise MemoryCatalogIntegrityError(f"artifact manifest {key} is invalid")
    return value


def _require_int(payload: object, key: str) -> int:
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError("artifact manifest object is invalid")
    value = payload.get(key)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise MemoryCatalogIntegrityError(f"artifact manifest {key} is invalid")
    return value


def _require_list(payload: object, key: str) -> list[object]:
    if not isinstance(payload, dict):
        raise MemoryCatalogIntegrityError("artifact manifest object is invalid")
    value = payload.get(key)
    if not isinstance(value, list):
        raise MemoryCatalogIntegrityError(f"artifact manifest {key} is invalid")
    return value
