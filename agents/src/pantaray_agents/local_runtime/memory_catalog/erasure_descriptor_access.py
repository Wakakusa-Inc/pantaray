from __future__ import annotations

import os
import shutil
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal, NamedTuple

from pantaray_agents.local_runtime.descriptor_access import (
    DescriptorPathError,
    DescriptorPathMissingError,
    open_directory_at_descriptor,
    open_directory_descriptor,
    open_regular_file_at_descriptor,
)

from .errors import MemoryCatalogIntegrityError

_PRIVATE_DIRECTORY_MODE = 0o700

type ErasureTargetKind = Literal["directory", "regular_file"]


@dataclass(frozen=True, slots=True)
class UserErasureFilesystemTarget:
    quarantine_name: str
    relative_path: str
    kind: ErasureTargetKind


class _FileIdentity(NamedTuple):
    device: int
    inode: int
    kind: int


@dataclass(frozen=True, slots=True)
class _PinnedTarget:
    parent_descriptor: int
    descriptor: int
    identity: _FileIdentity


def open_user_erasure_root_descriptor(*, root_path: Path) -> int:
    try:
        return open_directory_descriptor(root_path=root_path.absolute())
    except DescriptorPathError as exc:
        raise MemoryCatalogIntegrityError(
            "user erasure filesystem root is missing or unsafe"
        ) from exc


def quarantine_user_erasure_targets(
    *,
    root_descriptor: int,
    quarantine_relative_path: str,
    targets: tuple[UserErasureFilesystemTarget, ...],
) -> None:
    for target in targets:
        _quarantine_target(
            root_descriptor=root_descriptor,
            quarantine_relative_path=quarantine_relative_path,
            target=target,
        )


def remove_user_erasure_directory(*, root_descriptor: int, relative_path: str) -> None:
    if not shutil.rmtree.avoids_symlink_attacks:
        raise MemoryCatalogIntegrityError(
            "descriptor-safe recursive removal is required for user erasure"
        )
    parent_relative_path, name = _relative_parent_and_name(relative_path)
    parent_descriptor = _open_optional_directory(
        parent_descriptor=root_descriptor,
        relative_path=parent_relative_path,
    )
    if parent_descriptor is None:
        return
    directory_descriptor: int | None = None
    try:
        directory_descriptor = _open_optional_target(
            parent_descriptor=parent_descriptor,
            name=name,
            kind="directory",
        )
        if directory_descriptor is None:
            return
        identity = _identity(directory_descriptor)
        _require_entry_identity(
            parent_descriptor=parent_descriptor,
            name=name,
            expected=identity,
        )
        shutil.rmtree(name, dir_fd=parent_descriptor)
        if _entry_exists(parent_descriptor=parent_descriptor, name=name):
            raise MemoryCatalogIntegrityError(
                "user erasure directory remains after removal"
            )
        os.fsync(parent_descriptor)
    finally:
        if directory_descriptor is not None:
            os.close(directory_descriptor)
        os.close(parent_descriptor)


def verify_user_erasure_paths_absent(
    *,
    root_descriptor: int,
    quarantine_relative_path: str,
    targets: tuple[UserErasureFilesystemTarget, ...],
) -> None:
    if _root_relative_entry_exists(
        root_descriptor=root_descriptor,
        relative_path=quarantine_relative_path,
    ):
        raise MemoryCatalogIntegrityError("quarantined tenant artifacts remain")
    for target in targets:
        if _root_relative_entry_exists(
            root_descriptor=root_descriptor,
            relative_path=target.relative_path,
        ):
            raise MemoryCatalogIntegrityError("live user memory files remain")


def _quarantine_target(
    *,
    root_descriptor: int,
    quarantine_relative_path: str,
    target: UserErasureFilesystemTarget,
) -> None:
    source = _open_pinned_target(
        root_descriptor=root_descriptor,
        relative_path=target.relative_path,
        kind=target.kind,
    )
    destination_descriptor: int | None = None
    quarantined_descriptor: int | None = None
    try:
        destination_descriptor = _open_optional_directory(
            parent_descriptor=root_descriptor,
            relative_path=quarantine_relative_path,
        )
        if destination_descriptor is not None:
            quarantined_descriptor = _open_optional_target(
                parent_descriptor=destination_descriptor,
                name=target.quarantine_name,
                kind=target.kind,
            )
        if source is not None and quarantined_descriptor is not None:
            raise MemoryCatalogIntegrityError(
                "both live and quarantined tenant artifact roots exist"
            )
        if source is None:
            return
        if destination_descriptor is None:
            destination_descriptor = _open_or_create_directory_path(
                parent_descriptor=root_descriptor,
                relative_path=quarantine_relative_path,
            )
        source_name = _relative_parent_and_name(target.relative_path)[1]
        _require_entry_identity(
            parent_descriptor=source.parent_descriptor,
            name=source_name,
            expected=source.identity,
        )
        try:
            os.rename(
                source_name,
                target.quarantine_name,
                src_dir_fd=source.parent_descriptor,
                dst_dir_fd=destination_descriptor,
            )
        except FileNotFoundError as exc:
            raise MemoryCatalogIntegrityError(
                "live user erasure target changed before quarantine"
            ) from exc
        quarantined_descriptor = _open_required_target(
            parent_descriptor=destination_descriptor,
            name=target.quarantine_name,
            kind=target.kind,
        )
        if _identity(quarantined_descriptor) != source.identity:
            raise MemoryCatalogIntegrityError(
                "quarantined tenant artifact identity changed"
            )
        os.fsync(source.parent_descriptor)
        os.fsync(destination_descriptor)
    finally:
        if quarantined_descriptor is not None:
            os.close(quarantined_descriptor)
        if destination_descriptor is not None:
            os.close(destination_descriptor)
        if source is not None:
            os.close(source.descriptor)
            os.close(source.parent_descriptor)


def _open_pinned_target(
    *, root_descriptor: int, relative_path: str, kind: ErasureTargetKind
) -> _PinnedTarget | None:
    parent_relative_path, name = _relative_parent_and_name(relative_path)
    parent_descriptor = _open_optional_directory(
        parent_descriptor=root_descriptor,
        relative_path=parent_relative_path,
    )
    if parent_descriptor is None:
        return None
    try:
        descriptor = _open_optional_target(
            parent_descriptor=parent_descriptor,
            name=name,
            kind=kind,
        )
    except BaseException:
        os.close(parent_descriptor)
        raise
    if descriptor is None:
        os.close(parent_descriptor)
        return None
    try:
        return _PinnedTarget(parent_descriptor, descriptor, _identity(descriptor))
    except BaseException:
        os.close(descriptor)
        os.close(parent_descriptor)
        raise


def _open_optional_directory(
    *, parent_descriptor: int, relative_path: str
) -> int | None:
    try:
        return open_directory_at_descriptor(
            parent_descriptor=parent_descriptor,
            relative_path=relative_path,
        )
    except DescriptorPathMissingError:
        return None
    except DescriptorPathError as exc:
        raise MemoryCatalogIntegrityError(
            "user erasure directory path is unsafe"
        ) from exc


def _open_optional_target(
    *, parent_descriptor: int, name: str, kind: ErasureTargetKind
) -> int | None:
    try:
        if kind == "directory":
            return open_directory_at_descriptor(
                parent_descriptor=parent_descriptor,
                relative_path=name,
            )
        return open_regular_file_at_descriptor(
            parent_descriptor=parent_descriptor,
            relative_path=name,
        )
    except DescriptorPathMissingError:
        return None
    except DescriptorPathError as exc:
        raise MemoryCatalogIntegrityError("user erasure target path is unsafe") from exc


def _open_required_target(
    *, parent_descriptor: int, name: str, kind: ErasureTargetKind
) -> int:
    descriptor = _open_optional_target(
        parent_descriptor=parent_descriptor,
        name=name,
        kind=kind,
    )
    if descriptor is None:
        raise MemoryCatalogIntegrityError("quarantined tenant artifact is missing")
    return descriptor


def _open_or_create_directory_path(
    *, parent_descriptor: int, relative_path: str
) -> int:
    descriptor = _open_optional_directory(
        parent_descriptor=parent_descriptor,
        relative_path=".",
    )
    if descriptor is None:
        raise MemoryCatalogIntegrityError("user erasure root descriptor is unavailable")
    try:
        for component in _relative_components(relative_path):
            child = _open_optional_directory(
                parent_descriptor=descriptor,
                relative_path=component,
            )
            if child is None:
                try:
                    os.mkdir(
                        component,
                        mode=_PRIVATE_DIRECTORY_MODE,
                        dir_fd=descriptor,
                    )
                    os.fsync(descriptor)
                except FileExistsError:
                    pass
                child = _open_optional_directory(
                    parent_descriptor=descriptor,
                    relative_path=component,
                )
                if child is None:
                    raise MemoryCatalogIntegrityError(
                        "user erasure quarantine directory was not created"
                    )
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _root_relative_entry_exists(*, root_descriptor: int, relative_path: str) -> bool:
    parent_relative_path, name = _relative_parent_and_name(relative_path)
    parent_descriptor = _open_optional_directory(
        parent_descriptor=root_descriptor,
        relative_path=parent_relative_path,
    )
    if parent_descriptor is None:
        return False
    try:
        return _entry_exists(parent_descriptor=parent_descriptor, name=name)
    finally:
        os.close(parent_descriptor)


def _entry_exists(*, parent_descriptor: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError:
        return False
    return True


def _require_entry_identity(
    *, parent_descriptor: int, name: str, expected: _FileIdentity
) -> None:
    try:
        current = os.stat(name, dir_fd=parent_descriptor, follow_symlinks=False)
    except FileNotFoundError as exc:
        raise MemoryCatalogIntegrityError(
            "user erasure target identity changed"
        ) from exc
    if _identity(current) != expected:
        raise MemoryCatalogIntegrityError("user erasure target identity changed")


def _identity(value: int | os.stat_result) -> _FileIdentity:
    metadata = os.fstat(value) if isinstance(value, int) else value
    return _FileIdentity(
        metadata.st_dev, metadata.st_ino, stat.S_IFMT(metadata.st_mode)
    )


def _relative_parent_and_name(relative_path: str) -> tuple[str, str]:
    components = _relative_components(relative_path)
    return "/".join(components[:-1]) or ".", components[-1]


def _relative_components(relative_path: str) -> tuple[str, ...]:
    path = PurePosixPath(relative_path)
    if (
        not relative_path
        or path.is_absolute()
        or not path.parts
        or path.as_posix() != relative_path
        or any(part in {"", ".", ".."} or "\0" in part for part in path.parts)
    ):
        raise MemoryCatalogIntegrityError("user erasure path is not root-relative")
    return path.parts


__all__ = [
    "UserErasureFilesystemTarget",
    "open_user_erasure_root_descriptor",
    "quarantine_user_erasure_targets",
    "remove_user_erasure_directory",
    "verify_user_erasure_paths_absent",
]
