from __future__ import annotations

import errno
import os
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

from .paths import (
    ResolvedSandboxPath,
    SandboxPathError,
    SandboxPathErrorCode,
    resolve_sandbox_path,
)
from .policy import EditablePathPolicy


class TextFileErrorCode(StrEnum):
    TARGET_EXISTS = "TARGET_EXISTS"
    UNSUPPORTED_FILE = "UNSUPPORTED_FILE"
    IO_FAILED = "IO_FAILED"


class TextFileError(ValueError):
    def __init__(self, code: TextFileErrorCode | str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class TextSearchMatch:
    path: str
    line_number: int
    line: str


def read_text_file_raw(*, sandbox_root: Path, path: str) -> str:
    return read_text_file_from_root_raw(
        sandbox_root=sandbox_root,
        canonical_sandbox_root=None,
        path=path,
    )


def read_text_file_from_root_raw(
    *,
    sandbox_root: Path,
    canonical_sandbox_root: Path | None,
    path: str,
) -> str:
    resolved = resolve_sandbox_path(
        sandbox_root=sandbox_root,
        canonical_sandbox_root=canonical_sandbox_root,
        relative_path=path,
        must_exist=True,
        must_be_file=True,
    )
    return _read_raw(resolved.path)


def write_text_file_raw(
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    path: str,
    text: str,
) -> None:
    resolved = _resolve_writable_text_file(
        sandbox_root=sandbox_root,
        editable_policy=editable_policy,
        path=path,
    )
    _write_text_no_follow(path=resolved.path, text=text, exclusive=False)


def create_text_file_raw(
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    path: str,
    text: str,
) -> None:
    resolved = _resolve_writable_text_file(
        sandbox_root=sandbox_root,
        editable_policy=editable_policy,
        path=path,
    )
    if resolved.path.exists():
        raise TextFileError(
            TextFileErrorCode.TARGET_EXISTS,
            f"path already exists; use apply_patch to edit existing files: {resolved.relative_path}",
        )
    _write_text_no_follow(path=resolved.path, text=text, exclusive=True)


def _resolve_writable_text_file(
    *,
    sandbox_root: Path,
    editable_policy: EditablePathPolicy,
    path: str,
) -> ResolvedSandboxPath:
    resolved = resolve_sandbox_path(
        sandbox_root=sandbox_root,
        relative_path=path,
        must_exist=False,
        follow_final_symlink=False,
    )
    if resolved.path.is_symlink():
        raise SandboxPathError(
            SandboxPathErrorCode.PATH_DENIED,
            f"writable path must not be a symbolic link: {resolved.relative_path}",
        )
    canonical_relative_path = resolved.path.relative_to(resolved.root).as_posix()
    canonical_resolved = ResolvedSandboxPath(
        root=resolved.root,
        relative_path=canonical_relative_path,
        path=resolved.path,
    )
    editable_policy.require_editable(canonical_resolved)
    if resolved.path.exists() and not resolved.path.is_file():
        raise SandboxPathError(
            SandboxPathErrorCode.TARGET_NOT_FILE,
            f"path is not a file: {resolved.relative_path}",
        )
    resolved.path.parent.mkdir(parents=True, exist_ok=True)
    return canonical_resolved


def list_text_dir(*, sandbox_root: Path, path: str) -> tuple[str, ...]:
    resolved = resolve_sandbox_path(
        sandbox_root=sandbox_root,
        relative_path=path,
        must_exist=True,
        must_be_dir=True,
    )
    return tuple(sorted(child.name for child in resolved.path.iterdir()))


def search_text_files(
    *,
    sandbox_root: Path,
    query: str,
    limit: int,
    match_paths: bool = False,
    canonical_sandbox_root: Path | None = None,
) -> tuple[TextSearchMatch, ...]:
    if limit < 1:
        raise ValueError("limit must be >= 1")
    matches: list[TextSearchMatch] = []
    root = resolve_sandbox_path(
        sandbox_root=sandbox_root,
        canonical_sandbox_root=canonical_sandbox_root,
        relative_path=".",
        must_exist=True,
        must_be_dir=True,
    ).root
    for path in sorted(root.rglob("*")):
        if len(matches) >= limit:
            break
        if not path.is_file():
            continue
        relative_path = path.relative_to(root).as_posix()
        try:
            resolved = resolve_sandbox_path(
                sandbox_root=sandbox_root,
                canonical_sandbox_root=canonical_sandbox_root,
                relative_path=relative_path,
                must_exist=True,
                must_be_file=True,
            )
        except SandboxPathError:
            continue
        if match_paths and query in relative_path:
            matches.append(
                TextSearchMatch(
                    path=relative_path,
                    line_number=0,
                    line="",
                )
            )
            if len(matches) >= limit:
                break
        try:
            text = _read_raw(resolved.path)
        except TextFileError:
            continue
        for line_number, line in enumerate(text.splitlines(), start=1):
            if query in line:
                matches.append(
                    TextSearchMatch(
                        path=relative_path,
                        line_number=line_number,
                        line=line,
                    )
                )
                if len(matches) >= limit:
                    break
    return tuple(matches)


def _read_raw(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise TextFileError(
            TextFileErrorCode.UNSUPPORTED_FILE,
            f"file is not valid utf-8 text: {path}",
        ) from exc
    except OSError as exc:
        raise TextFileError(
            TextFileErrorCode.IO_FAILED,
            f"failed to read text file {path}: {exc}",
        ) from exc


def _write_text_no_follow(*, path: Path, text: str, exclusive: bool) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW
    flags |= os.O_EXCL if exclusive else os.O_TRUNC
    try:
        descriptor = os.open(path, flags, 0o666)
    except FileExistsError as exc:
        raise TextFileError(
            TextFileErrorCode.TARGET_EXISTS,
            f"path already exists; use apply_patch to edit existing files: {path}",
        ) from exc
    except OSError as exc:
        if exc.errno == errno.ELOOP:
            raise SandboxPathError(
                SandboxPathErrorCode.PATH_DENIED,
                f"writable path must not be a symbolic link: {path}",
            ) from exc
        raise
    with os.fdopen(descriptor, "wb") as file:
        file.write(text.encode("utf-8"))
