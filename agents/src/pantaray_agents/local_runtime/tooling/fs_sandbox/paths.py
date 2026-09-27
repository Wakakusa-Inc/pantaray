from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from ..workspace_root_authority import (
    WorkspaceRootAuthorityError,
    WorkspaceRootAuthorityErrorCode,
    validate_workspace_root,
)


class SandboxPathErrorCode(StrEnum):
    PATH_DENIED = "PATH_DENIED"
    PATH_NOT_FOUND = "PATH_NOT_FOUND"
    TARGET_NOT_FILE = "TARGET_NOT_FILE"
    TARGET_NOT_DIR = "TARGET_NOT_DIR"


class SandboxPathError(ValueError):
    def __init__(self, code: SandboxPathErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class ResolvedSandboxPath:
    root: Path
    relative_path: str
    path: Path


def resolve_sandbox_path(
    *,
    sandbox_root: Path,
    canonical_sandbox_root: Path | None = None,
    relative_path: str,
    must_exist: bool,
    must_be_file: bool = False,
    must_be_dir: bool = False,
    follow_final_symlink: bool = True,
) -> ResolvedSandboxPath:
    root = _resolve_sandbox_root(
        sandbox_root=sandbox_root,
        canonical_sandbox_root=canonical_sandbox_root,
    )
    raw = _validate_relative_path(relative_path)
    candidate = root / raw
    resolved = _resolve_candidate(
        candidate=candidate,
        must_exist=must_exist,
        follow_final_symlink=follow_final_symlink,
    )
    _ensure_contained(root=root, path=resolved)
    if must_exist and not _path_entry_exists(resolved):
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_NOT_FOUND,
            f"path does not exist: {raw}",
        )
    if must_be_file and not resolved.is_file():
        raise SandboxPathError(
            SandboxPathErrorCode.TARGET_NOT_FILE,
            f"path is not a file: {raw}",
        )
    if must_be_dir and not resolved.is_dir():
        raise SandboxPathError(
            SandboxPathErrorCode.TARGET_NOT_DIR,
            f"path is not a directory: {raw}",
        )
    return ResolvedSandboxPath(root=root, relative_path=raw, path=resolved)


def _validate_relative_path(relative_path: str) -> str:
    raw = relative_path.strip()
    if not raw:
        raise SandboxPathError(SandboxPathErrorCode.PATH_DENIED, "path is empty")
    path = Path(raw)
    if path.is_absolute():
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            "absolute paths are not allowed",
        )
    if any(part == ".." for part in path.parts):
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            "parent directory traversal is not allowed",
        )
    if any(part == "" for part in path.parts):
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            "empty path segments are not allowed",
        )
    return path.as_posix()


def _resolve_sandbox_root(
    *,
    sandbox_root: Path,
    canonical_sandbox_root: Path | None,
) -> Path:
    if canonical_sandbox_root is None:
        return sandbox_root.resolve(strict=True)
    try:
        return validate_workspace_root(
            real_path=sandbox_root,
            canonical_real_path=canonical_sandbox_root,
        ).canonical_real_path
    except WorkspaceRootAuthorityError as exc:
        code = (
            SandboxPathErrorCode.PATH_NOT_FOUND
            if exc.code == WorkspaceRootAuthorityErrorCode.ROOT_NOT_FOUND
            else SandboxPathErrorCode.PATH_DENIED
        )
        raise SandboxPathError(code, str(exc)) from exc


def _resolve_candidate(
    *, candidate: Path, must_exist: bool, follow_final_symlink: bool
) -> Path:
    try:
        if not follow_final_symlink:
            return candidate.parent.resolve(strict=must_exist) / candidate.name
        if must_exist:
            return candidate.resolve(strict=True)
        return candidate.resolve(strict=False)
    except FileNotFoundError as exc:
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_NOT_FOUND,
            f"path does not exist: {candidate}",
        ) from exc


def _path_entry_exists(path: Path) -> bool:
    return path.exists() or path.is_symlink()


def _ensure_contained(*, root: Path, path: Path) -> None:
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            "resolved path escapes the sandbox root",
        ) from exc
