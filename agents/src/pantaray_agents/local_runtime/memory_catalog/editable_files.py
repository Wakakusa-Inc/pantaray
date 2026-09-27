"""Current memory files, with a short OS lock shared by writers and index readers."""

from __future__ import annotations

import errno
import fcntl
import hashlib
import json
import os
import unicodedata
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathMissingError,
    open_directory_at_descriptor,
    open_directory_descriptor,
    open_regular_file_at_descriptor,
)
from pantaray_agents.local_runtime.descriptor_write import (
    CommittedFileWriteError,
    open_writable_parent_at_descriptor,
    open_writable_parent_descriptor,
    write_text_at_descriptor,
)

from .artifact_paths import tenant_artifact_relative_path
from .draft import validate_memory_documents
from .models import MemoryDocument

EditableMemorySource = Literal["fact", "long_term_insight", "agent_experience"]
EDITABLE_MEMORY_ROOTS: dict[str, EditableMemorySource] = {
    "facts": "fact",
    "insights": "long_term_insight",
    "agent_experience": "agent_experience",
}
MEMORY_AGENT_EDITABLE_ROOTS = ("facts", "insights")
# Current Markdown snapshots fit the existing editor's 1 MiB/file, 8 MiB scan
# budget. Raise these limits only when a required memory document exceeds them.
MAX_MEMORY_FILE_BYTES = 1024 * 1024
MAX_MEMORY_TOTAL_BYTES = 8 * 1024 * 1024
MAX_MEMORY_TREE_ENTRIES = 20_000
# Depth bounds open directory handles; use iterative scans if a required layout
# exceeds 32 directory levels.
MAX_MEMORY_DIRECTORY_DEPTH = 32


class MemoryFileConflictError(RuntimeError):
    """The current file differs from the content used to prepare an edit."""


def memory_files_revision(documents: tuple[MemoryDocument, ...]) -> str:
    """Hash current paths and raw text; this creates no saved revision or history."""
    body = json.dumps(
        [(item.source_path, item.content) for item in documents],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(body.encode('utf-8')).hexdigest()}"


@dataclass(slots=True)
class _ReadBudget:
    remaining_bytes: int
    remaining_entries: int


def editable_memory_relative_path(user_id: str) -> str:
    return f"{tenant_artifact_relative_path(user_id)}/files"


def create_editable_memory_root(*, artifact_root: Path, user_id: str) -> Path:
    """Initialize the private root; ordinary reads never recreate a missing root."""
    relative_path = editable_memory_relative_path(user_id)
    parent, name = open_writable_parent_descriptor(
        root_path=artifact_root, relative_path=relative_path, create_missing=True
    )
    try:
        try:
            os.mkdir(name, mode=0o700, dir_fd=parent)
        except FileExistsError:
            pass
        descriptor = open_directory_at_descriptor(
            parent_descriptor=parent, relative_path=name
        )
        try:
            os.fchmod(descriptor, 0o700)
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.fsync(parent)
    finally:
        os.close(parent)
    return artifact_root / relative_path


@contextmanager
def locked_memory_files(*, artifact_root: Path, user_id: str) -> Iterator[MemoryFiles]:
    """Serialize Pantaray writers and index readers, including the DB commit.

    External edits are observed on read. Simultaneous writes require the same
    advisory lock; the OS cannot serialize a non-cooperating external editor.
    """
    relative_path = editable_memory_relative_path(user_id)
    descriptor = open_directory_descriptor(
        root_path=artifact_root, relative_path=relative_path
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield MemoryFiles(descriptor, user_id)
    finally:
        os.close(descriptor)


@dataclass(frozen=True, slots=True)
class MemoryFiles:
    """Operations available only within ``locked_memory_files``."""

    descriptor: int
    user_id: str

    def documents(self) -> tuple[MemoryDocument, ...]:
        return self._snapshot()[0]

    def _snapshot(
        self, *, reclaimed_bytes: int = 0
    ) -> tuple[tuple[MemoryDocument, ...], _ReadBudget]:
        documents: list[MemoryDocument] = []
        budget = _ReadBudget(
            MAX_MEMORY_TOTAL_BYTES + reclaimed_bytes, MAX_MEMORY_TREE_ENTRIES
        )
        for category in EDITABLE_MEMORY_ROOTS:
            try:
                child = open_directory_at_descriptor(
                    parent_descriptor=self.descriptor, relative_path=category
                )
            except DescriptorPathMissingError:
                continue
            try:
                _consume_entry(budget, category)
                documents.extend(
                    sorted(
                        _read_documents(child, category, budget),
                        key=lambda item: item.source_path,
                    )
                )
            finally:
                os.close(child)
        return tuple(documents), budget

    def read(self, path: str) -> str:
        validate_editable_memory_path(path)
        return _read_text(self.descriptor, path)

    def write(self, *, path: str, text: str, expected_text: str | None) -> None:
        validate_editable_memory_path(path)
        text_bytes = len(text.encode("utf-8"))
        if text_bytes > MAX_MEMORY_FILE_BYTES:
            raise OSError(
                errno.EFBIG, f"memory file exceeds {MAX_MEMORY_FILE_BYTES} bytes", path
            )
        self._require_current(path, expected_text)
        increase = text_bytes - len((expected_text or "").encode("utf-8"))
        documents, budget = self._snapshot(reclaimed_bytes=max(0, -increase))
        if (
            sum(len(item.content.encode("utf-8")) for item in documents) + increase
            > MAX_MEMORY_TOTAL_BYTES
        ):
            raise OSError(
                errno.EFBIG, f"memory tree exceeds {MAX_MEMORY_TOTAL_BYTES} bytes", path
            )
        self._require_entry_capacity(path, budget.remaining_entries)
        parent, name = open_writable_parent_at_descriptor(
            root_descriptor=self.descriptor, relative_path=path, create_missing=True
        )
        try:
            write_text_at_descriptor(
                parent_descriptor=parent,
                destination_name=name,
                text=text,
                replacement_mode=0o600,
                exclusive=expected_text is None,
            )
        finally:
            os.close(parent)

    def delete(self, *, path: str, expected_text: str) -> None:
        validate_editable_memory_path(path)
        self._require_current(path, expected_text)
        parent, name = open_writable_parent_at_descriptor(
            root_descriptor=self.descriptor, relative_path=path, create_missing=False
        )
        try:
            os.unlink(name, dir_fd=parent)
            try:
                os.fsync(parent)
            except OSError as error:
                raise CommittedFileWriteError(
                    error.errno,
                    f"file was deleted, but directory sync failed: {error}",
                    path,
                ) from error
        finally:
            os.close(parent)

    def move(self, *, source: str, destination: str, expected_text: str) -> None:
        validate_editable_memory_path(source)
        validate_editable_memory_path(destination)
        if PurePosixPath(source).parts[0] != PurePosixPath(destination).parts[0]:
            raise ValueError("memory files cannot move between editable categories")
        self._require_current(source, expected_text)
        _, budget = self._snapshot()
        self._require_entry_capacity(destination, budget.remaining_entries + 1)
        source_parent, source_name = open_writable_parent_at_descriptor(
            root_descriptor=self.descriptor, relative_path=source, create_missing=False
        )
        try:
            destination_parent, destination_name = open_writable_parent_at_descriptor(
                root_descriptor=self.descriptor,
                relative_path=destination,
                create_missing=True,
            )
            try:
                case_alias = _is_case_alias(
                    source_parent, source_name, destination_parent, destination_name
                )
                if case_alias:
                    os.rename(
                        source_name,
                        destination_name,
                        src_dir_fd=source_parent,
                        dst_dir_fd=destination_parent,
                    )
                else:
                    self._require_current(destination, None)
                    os.link(
                        source_name,
                        destination_name,
                        src_dir_fd=source_parent,
                        dst_dir_fd=destination_parent,
                        follow_symlinks=False,
                    )
                try:
                    # Persist the destination before removing the only old name.
                    os.fsync(destination_parent)
                    if not case_alias:
                        os.unlink(source_name, dir_fd=source_parent)
                        os.fsync(source_parent)
                except OSError as error:
                    raise CommittedFileWriteError(
                        error.errno,
                        f"destination was created; re-read both move paths: {error}",
                        destination,
                    ) from error
            finally:
                os.close(destination_parent)
        finally:
            os.close(source_parent)

    def _require_entry_capacity(self, path: str, remaining: int) -> None:
        parts = PurePosixPath(path).parts
        parent = os.dup(self.descriptor)
        try:
            for index, part in enumerate(parts):
                try:
                    if index == len(parts) - 1:
                        os.stat(part, dir_fd=parent, follow_symlinks=False)
                        return
                    child = open_directory_at_descriptor(
                        parent_descriptor=parent, relative_path=part
                    )
                except (DescriptorPathMissingError, FileNotFoundError):
                    if len(parts) - index > remaining:
                        raise OSError(
                            errno.EFBIG,
                            f"memory tree exceeds {MAX_MEMORY_TREE_ENTRIES} entries",
                            path,
                        ) from None
                    return
                os.close(parent)
                parent = child
        finally:
            os.close(parent)

    def _require_current(self, path: str, expected_text: str | None) -> None:
        try:
            current = _read_text(self.descriptor, path)
        except DescriptorPathMissingError:
            current = None
        if current != expected_text:
            raise MemoryFileConflictError(
                f"memory file changed; re-read before editing: {path}"
            )


def validate_editable_memory_path(path: str) -> None:
    validate_memory_documents((MemoryDocument(path, ""),))
    parts = PurePosixPath(path).parts
    if len(parts) < 2 or parts[0] not in EDITABLE_MEMORY_ROOTS:
        raise ValueError("memory file path must belong to an editable category")
    if len(parts) - 1 > MAX_MEMORY_DIRECTORY_DEPTH:
        raise ValueError(
            f"memory file path exceeds {MAX_MEMORY_DIRECTORY_DEPTH} directory levels"
        )
    if (
        any(part.startswith(".") for part in parts)
        or PurePosixPath(path).suffix.lower() != ".md"
    ):
        raise ValueError("memory file path must be a visible Markdown file")


def _read_text(
    descriptor: int, relative_path: str, *, max_bytes: int = MAX_MEMORY_FILE_BYTES
) -> str:
    file_descriptor = open_regular_file_at_descriptor(
        parent_descriptor=descriptor, relative_path=relative_path
    )
    with os.fdopen(file_descriptor, "rb") as handle:
        if os.fstat(handle.fileno()).st_size > max_bytes:
            raise OSError(
                errno.EFBIG, f"memory read exceeds {max_bytes} bytes", relative_path
            )
        data = handle.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise OSError(
                errno.EFBIG, f"memory read exceeds {max_bytes} bytes", relative_path
            )
        return data.decode("utf-8")


def _read_documents(
    descriptor: int, prefix: str, budget: _ReadBudget
) -> Iterator[MemoryDocument]:
    with os.scandir(descriptor) as entries:
        for entry in entries:
            _consume_entry(budget, prefix)
            if entry.name.startswith("."):
                continue
            path = f"{prefix}/{entry.name}"
            if entry.is_dir(follow_symlinks=False):
                if len(PurePosixPath(path).parts) > MAX_MEMORY_DIRECTORY_DEPTH:
                    raise OSError(
                        errno.EFBIG,
                        f"memory tree exceeds {MAX_MEMORY_DIRECTORY_DEPTH} directory levels",
                        path,
                    )
                child = open_directory_at_descriptor(
                    parent_descriptor=descriptor, relative_path=entry.name
                )
                try:
                    yield from _read_documents(child, path, budget)
                finally:
                    os.close(child)
            elif PurePosixPath(entry.name).suffix.lower() == ".md":
                content = _read_text(
                    descriptor,
                    entry.name,
                    max_bytes=min(MAX_MEMORY_FILE_BYTES, budget.remaining_bytes),
                )
                budget.remaining_bytes -= len(content.encode("utf-8"))
                yield MemoryDocument(path, content)


def _consume_entry(budget: _ReadBudget, path: str) -> None:
    budget.remaining_entries -= 1
    if budget.remaining_entries < 0:
        raise OSError(
            errno.EFBIG, f"memory tree exceeds {MAX_MEMORY_TREE_ENTRIES} entries", path
        )


def _is_case_alias(
    source_parent: int, source: str, destination_parent: int, destination: str
) -> bool:
    if unicodedata.normalize("NFD", source.casefold()) != unicodedata.normalize(
        "NFD", destination.casefold()
    ):
        return False
    try:
        target = os.stat(destination, dir_fd=destination_parent, follow_symlinks=False)
    except FileNotFoundError:
        return False
    if not os.path.samestat(
        os.fstat(source_parent), os.fstat(destination_parent)
    ) or not os.path.samestat(
        os.stat(source, dir_fd=source_parent, follow_symlinks=False), target
    ):
        return False
    with os.scandir(destination_parent) as entries:
        for count, entry in enumerate(entries, start=1):
            if count > MAX_MEMORY_TREE_ENTRIES:
                raise OSError(errno.EFBIG, "memory directory has too many entries")
            if entry.name == destination:
                return False
    return True
