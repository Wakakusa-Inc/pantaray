from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class WorkspaceRootAuthorityErrorCode(StrEnum):
    ROOT_NOT_FOUND = "ROOT_NOT_FOUND"
    ROOT_NOT_DIRECTORY = "ROOT_NOT_DIRECTORY"
    ROOT_IDENTITY_CHANGED = "ROOT_IDENTITY_CHANGED"


class WorkspaceRootAuthorityError(ValueError):
    def __init__(
        self,
        code: WorkspaceRootAuthorityErrorCode,
        message: str,
    ) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ValidatedWorkspaceRoot:
    real_path: Path
    canonical_real_path: Path


def validate_workspace_root(
    *,
    real_path: Path,
    canonical_real_path: Path,
) -> ValidatedWorkspaceRoot:
    """Verify that a registered path still resolves to its approved target."""

    raw = _normalized_absolute_path(real_path, field_name="real_path")
    expected = _normalized_absolute_path(
        canonical_real_path,
        field_name="canonical_real_path",
    )
    try:
        current = raw.resolve(strict=True)
    except FileNotFoundError as exc:
        raise WorkspaceRootAuthorityError(
            WorkspaceRootAuthorityErrorCode.ROOT_NOT_FOUND,
            f"registered workspace root does not exist: {raw}",
        ) from exc
    except OSError as exc:
        raise WorkspaceRootAuthorityError(
            WorkspaceRootAuthorityErrorCode.ROOT_IDENTITY_CHANGED,
            f"registered workspace root cannot be verified: {raw}",
        ) from exc
    if current != expected:
        raise WorkspaceRootAuthorityError(
            WorkspaceRootAuthorityErrorCode.ROOT_IDENTITY_CHANGED,
            "registered workspace root no longer resolves to its approved target",
        )
    if not current.is_dir():
        raise WorkspaceRootAuthorityError(
            WorkspaceRootAuthorityErrorCode.ROOT_NOT_DIRECTORY,
            f"registered workspace root is not a directory: {raw}",
        )
    return ValidatedWorkspaceRoot(
        real_path=raw,
        canonical_real_path=expected,
    )


def _normalized_absolute_path(path: Path, *, field_name: str) -> Path:
    if not path.is_absolute():
        raise WorkspaceRootAuthorityError(
            WorkspaceRootAuthorityErrorCode.ROOT_IDENTITY_CHANGED,
            f"registered workspace {field_name} must be absolute",
        )
    return Path(os.path.normpath(str(path)))


__all__ = [
    "ValidatedWorkspaceRoot",
    "WorkspaceRootAuthorityError",
    "WorkspaceRootAuthorityErrorCode",
    "validate_workspace_root",
]
