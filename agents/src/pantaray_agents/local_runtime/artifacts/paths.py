from __future__ import annotations

from pathlib import Path, PurePosixPath

from ..storage.migrations import MigrationError
from .models import ArtifactKind, ManagedArtifactLocation

ARTIFACT_TEMP_DIRNAME = ".tmp"
_ARTIFACT_KIND_DIRS: dict[ArtifactKind, str] = {
    "screenshots": "screenshots",
    "long_term_insight": "long_term_insight",
    "facts": "facts",
    "generated": "generated",
}


def normalize_artifact_root(root_path: Path) -> Path:
    normalized = Path(root_path).expanduser()
    if not str(normalized).strip():
        raise MigrationError("LOCAL_ARTIFACT_ROOT must not be empty")
    return normalized.resolve()


def required_artifact_subdirectories() -> tuple[str, ...]:
    return tuple(_ARTIFACT_KIND_DIRS.values()) + (ARTIFACT_TEMP_DIRNAME,)


def artifact_kind_directory(kind: ArtifactKind) -> str:
    return _ARTIFACT_KIND_DIRS[kind]


def validate_relative_artifact_path(relative_path: str) -> str:
    normalized = relative_path.strip().replace("\\", "/")
    if not normalized:
        raise MigrationError("artifact relative path must not be empty")
    pure_path = PurePosixPath(normalized)
    if pure_path.is_absolute():
        raise MigrationError("artifact relative path must not be absolute")
    if any(part in {"", ".", ".."} for part in pure_path.parts):
        raise MigrationError("artifact relative path contains forbidden traversal")
    return str(pure_path)


def resolve_artifact_path(*, root_path: Path, relative_path: str) -> Path:
    normalized_root = normalize_artifact_root(root_path)
    normalized_relative = validate_relative_artifact_path(relative_path)
    resolved = (normalized_root / normalized_relative).resolve()
    try:
        resolved.relative_to(normalized_root)
    except ValueError as exc:
        raise MigrationError("artifact path escapes LOCAL_ARTIFACT_ROOT") from exc
    return resolved


def build_managed_artifact_location(
    *,
    root_path: Path,
    kind: ArtifactKind,
    artifact_id: str,
    file_name: str,
) -> ManagedArtifactLocation:
    normalized_artifact_id = validate_relative_artifact_path(artifact_id)
    normalized_file_name = validate_relative_artifact_path(file_name)
    if "/" in normalized_file_name:
        raise MigrationError("file_name must be a single path segment")
    relative_path = "/".join(
        (artifact_kind_directory(kind), normalized_artifact_id, normalized_file_name)
    )
    return ManagedArtifactLocation(
        kind=kind,
        relative_path=relative_path,
        absolute_path=resolve_artifact_path(
            root_path=root_path,
            relative_path=relative_path,
        ),
    )
