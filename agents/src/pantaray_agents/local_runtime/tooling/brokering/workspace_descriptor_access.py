from __future__ import annotations

import errno
import os
import stat
import time
from collections.abc import Callable, Generator
from fnmatch import fnmatch
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple

import regex  # type: ignore[import-untyped]

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathError,
    DescriptorPathMissingError,
    DescriptorPathPolicyError,
    open_directory_descriptor,
    open_regular_file_descriptor,
)

from .broker_common import BrokerPolicyError

_DIRECTORY_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
_FILE_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK
_WORKSPACE_FILE_POLICY_ERROR = (
    "workspace path is missing, not a regular file, or uses a symlink"
)
SEARCH_TIMEOUT_SECONDS = 5.0
GREP_MAX_FILE_BYTES = 1024 * 1024
GREP_MAX_MATCH_CHARS = 500

type DescriptorTruncationReason = Literal["limit", "scan_budget", "timeout"]


class WorkspaceDescriptorEntry(NamedTuple):
    root_relative_path: str
    kind: Literal["file", "directory"]


class WorkspaceDescriptorScan(NamedTuple):
    entries: tuple[WorkspaceDescriptorEntry, ...]
    truncation_reason: DescriptorTruncationReason | None


class WorkspaceGrepMatch(NamedTuple):
    path: str
    line_number: int
    line: str


class WorkspaceGrepScan(NamedTuple):
    matches: tuple[WorkspaceGrepMatch, ...]
    truncation_reason: DescriptorTruncationReason | None
    skipped_files: int


class _ScanLimitReached(RuntimeError): ...


class WorkspacePathMissingError(BrokerPolicyError):
    """Raised when a required workspace path component does not exist."""


def open_workspace_file_descriptor(*, root_path: Path, relative_path: str) -> int:
    try:
        return open_regular_file_descriptor(
            root_path=root_path,
            relative_path=relative_path,
        )
    except DescriptorPathMissingError as exc:
        raise WorkspacePathMissingError(_WORKSPACE_FILE_POLICY_ERROR) from exc
    except DescriptorPathPolicyError as exc:
        raise BrokerPolicyError(_WORKSPACE_FILE_POLICY_ERROR) from exc


def open_workspace_entry_descriptor(*, root_path: Path, relative_path: str) -> int:
    """Open a file or directory below root without following any symlink.

    The caller reads the kind from the descriptor. Opened like a file so a FIFO
    does not block; a directory opened this way still lists with os.scandir.
    """

    components = _relative_components(relative_path, allow_dot=True)
    if not components:
        return _open_directory(root_path, ".")
    parent = _open_directory(root_path, "/".join(components[:-1]) or ".")
    try:
        return _open(components[-1], _FILE_FLAGS, parent=parent)
    finally:
        os.close(parent)


def scan_workspace_entries(
    *,
    root_path: Path,
    base_path: str,
    max_depth: int | None,
    limit: int,
    scan_limit: int,
    include_path: Callable[[Path], bool] | None = None,
    exclude_subtree: Callable[[Path], bool] | None = None,
    file_pattern: str | None = None,
    deadline: float | None = None,
) -> WorkspaceDescriptorScan:
    """Scan entries under base_path.

    include_path filters entries after they are opened and still walks into a
    directory it drops. exclude_subtree drops an entry before it is opened, and
    neither it nor anything under it is walked or charged to the scan budget.
    """

    selected: list[WorkspaceDescriptorEntry] = []
    iterator = _entries(
        root_path=root_path,
        base_path=base_path,
        max_depth=max_depth,
        scan_limit=scan_limit,
        deadline=deadline,
        exclude_subtree=exclude_subtree,
    )
    reason: DescriptorTruncationReason | None = None
    prefix = "" if base_path == "." else f"{base_path}/"
    try:
        for entry, _descriptor in iterator:
            relative = entry.root_relative_path.removeprefix(prefix)
            path = root_path.joinpath(*entry.root_relative_path.split("/"))
            if include_path is not None and not include_path(path):
                continue
            if file_pattern is not None and (
                entry.kind != "file"
                or not matches_workspace_glob(relative, file_pattern)
            ):
                continue
            if len(selected) >= limit:
                reason = "limit"
                break
            selected.append(entry)
    except _ScanLimitReached:
        reason = "scan_budget"
    except TimeoutError:
        reason = "timeout"
    finally:
        iterator.close()
    entries = tuple(sorted(selected, key=lambda item: item.root_relative_path))
    return WorkspaceDescriptorScan(entries, reason)


def glob_workspace_files(
    *,
    root_path: Path,
    base_path: str,
    pattern: str,
    limit: int,
    scan_limit: int,
    exclude_subtree: Callable[[Path], bool] | None = None,
) -> WorkspaceDescriptorScan:
    return scan_workspace_entries(
        root_path=root_path,
        base_path=base_path,
        max_depth=None,
        limit=limit,
        scan_limit=scan_limit,
        exclude_subtree=exclude_subtree,
        file_pattern=pattern,
        deadline=time.monotonic() + SEARCH_TIMEOUT_SECONDS,
    )


def grep_workspace_files(
    *,
    root_path: Path,
    base_path: str,
    pattern: str,
    include_glob: str | None,
    max_matches: int,
    scan_limit: int,
    exclude_subtree: Callable[[Path], bool] | None = None,
) -> WorkspaceGrepScan:
    deadline = time.monotonic() + SEARCH_TIMEOUT_SECONDS
    try:
        expression = regex.compile(pattern)
    except (regex.error, RecursionError) as exc:
        raise BrokerPolicyError(
            "grep pattern is invalid",
            code="GREP_PATTERN_INVALID",
            fix_hint="grep.pattern must be a valid regular expression.",
        ) from exc
    matches: list[WorkspaceGrepMatch] = []
    skipped_files = 0
    reason: DescriptorTruncationReason | None = None
    prefix = "" if base_path == "." else f"{base_path}/"
    iterator = _entries(
        root_path=root_path,
        base_path=base_path,
        max_depth=None,
        scan_limit=scan_limit,
        deadline=deadline,
        exclude_subtree=exclude_subtree,
    )
    try:
        for entry, descriptor in iterator:
            relative = entry.root_relative_path.removeprefix(prefix)
            if entry.kind != "file" or (
                include_glob is not None
                and not matches_workspace_glob(relative, include_glob)
            ):
                continue
            payload = _read_grep_descriptor(descriptor)
            if payload is None:
                skipped_files += 1
                continue
            for line_number, line in enumerate(payload.splitlines(), start=1):
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError
                if expression.search(line, timeout=remaining) is None:
                    continue
                if len(matches) >= max_matches:
                    reason = "limit"
                    break
                line = bound_grep_line(line)
                matches.append(
                    WorkspaceGrepMatch(entry.root_relative_path, line_number, line)
                )
            if reason == "limit":
                break
    except TimeoutError:
        reason = "timeout"
    except _ScanLimitReached:
        reason = "scan_budget"
    finally:
        iterator.close()
    ordered = tuple(sorted(matches, key=lambda item: (item.path, item.line_number)))
    return WorkspaceGrepScan(ordered, reason, skipped_files)


def matches_workspace_glob(path: str, pattern: str) -> bool:
    return fnmatch(path, pattern) or (
        pattern.startswith("**/") and fnmatch(path, pattern.removeprefix("**/"))
    )


def bound_grep_line(text: str) -> str:
    if len(text) <= GREP_MAX_MATCH_CHARS:
        return text
    return text[:GREP_MAX_MATCH_CHARS].rstrip() + "... [truncated]"


def _entries(
    *,
    root_path: Path,
    base_path: str,
    max_depth: int | None,
    scan_limit: int,
    deadline: float | None,
    exclude_subtree: Callable[[Path], bool] | None,
) -> Generator[tuple[WorkspaceDescriptorEntry, int], None, None]:
    base = _open_directory(root_path, base_path)
    relative = "/".join(_relative_components(base_path, allow_dot=True)) or "."
    excluded = (
        None
        if exclude_subtree is None
        else lambda child: exclude_subtree(root_path.joinpath(*child.split("/")))
    )
    try:
        yield from _walk(
            base, relative, 0, max_depth, [0], scan_limit, deadline, excluded
        )
    finally:
        os.close(base)


def _walk(
    descriptor: int,
    relative: str,
    depth: int,
    max_depth: int | None,
    scanned: list[int],
    scan_limit: int,
    deadline: float | None,
    excluded: Callable[[str], bool] | None,
) -> Generator[tuple[WorkspaceDescriptorEntry, int], None, None]:
    try:
        context = os.scandir(descriptor)
    except OSError as exc:
        _raise_policy(exc)
        raise
    with context as iterator:
        for item in iterator:
            if deadline is not None and time.monotonic() >= deadline:
                raise TimeoutError
            child_relative = item.name if relative == "." else f"{relative}/{item.name}"
            if excluded is not None and excluded(child_relative):
                continue
            scanned[0] += 1
            if scanned[0] > scan_limit:
                raise _ScanLimitReached
            try:
                if item.is_symlink():
                    continue
                is_directory = item.is_dir(follow_symlinks=False)
            except OSError as exc:
                _raise_policy(exc)
                raise
            child_depth = depth + 1
            if max_depth is not None and child_depth > max_depth:
                continue
            flags = _DIRECTORY_FLAGS if is_directory else _FILE_FLAGS
            child = _open(item.name, flags, parent=descriptor)
            try:
                mode = os.fstat(child).st_mode
                if is_directory:
                    if not stat.S_ISDIR(mode):
                        raise BrokerPolicyError(
                            "workspace path must reference a directory"
                        )
                    yield WorkspaceDescriptorEntry(child_relative, "directory"), child
                    if max_depth is None or child_depth < max_depth:
                        yield from _walk(
                            child,
                            child_relative,
                            child_depth,
                            max_depth,
                            scanned,
                            scan_limit,
                            deadline,
                            excluded,
                        )
                elif stat.S_ISREG(mode):
                    yield WorkspaceDescriptorEntry(child_relative, "file"), child
            finally:
                os.close(child)


def _open_directory(root_path: Path, relative_path: str) -> int:
    try:
        return open_directory_descriptor(
            root_path=root_path,
            relative_path=relative_path,
        )
    except DescriptorPathError as exc:
        raise BrokerPolicyError(
            "workspace path is missing, not a directory, or uses a symlink"
        ) from exc


def _open(component: str, flags: int, *, parent: int | None = None) -> int:
    try:
        if parent is None:
            return os.open(component, flags)
        return os.open(component, flags, dir_fd=parent)
    except OSError as exc:
        _raise_policy(exc)
        raise


def _raise_policy(exc: OSError) -> None:
    if exc.errno in {errno.ELOOP, errno.ENOENT, errno.ENOTDIR}:
        raise BrokerPolicyError(
            "workspace path is missing, not a directory, or uses a symlink"
        ) from exc


def _relative_components(value: str, *, allow_dot: bool) -> tuple[str, ...]:
    if value == ".":
        if allow_dot:
            return ()
        raise BrokerPolicyError("workspace path must reference a file")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or not path.parts:
        raise BrokerPolicyError("workspace path must be root-relative")
    if any(
        component in {"", ".", ".."} or "\0" in component for component in path.parts
    ):
        raise BrokerPolicyError("workspace path contains an unsafe component")
    return path.parts


def _read_grep_descriptor(descriptor: int) -> str | None:
    if os.fstat(descriptor).st_size > GREP_MAX_FILE_BYTES:
        return None
    with open(descriptor, "rb", closefd=False) as handle:
        payload = handle.read(GREP_MAX_FILE_BYTES + 1)
    if len(payload) > GREP_MAX_FILE_BYTES or b"\0" in payload:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None
