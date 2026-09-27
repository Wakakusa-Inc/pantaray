from __future__ import annotations

import errno
import os
import stat
from pathlib import Path, PurePosixPath

_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_DIRECTORY
_FILE_OPEN_FLAGS = os.O_RDONLY | os.O_CLOEXEC | os.O_NOFOLLOW | os.O_NONBLOCK


class DescriptorPathError(RuntimeError):
    """Base error for paths that cannot be safely opened below a fixed root."""


class DescriptorPathMissingError(DescriptorPathError):
    """Raised when a required descriptor path component does not exist."""


class DescriptorPathPolicyError(DescriptorPathError):
    """Raised when a descriptor path is unsafe or has the wrong file type."""


def open_directory_descriptor(*, root_path: Path, relative_path: str = ".") -> int:
    root_descriptor = _open_trusted_root(root_path)
    try:
        return _open_directory_components(
            parent_descriptor=root_descriptor,
            components=_relative_components(relative_path, allow_dot=True),
        )
    finally:
        os.close(root_descriptor)


def open_directory_at_descriptor(*, parent_descriptor: int, relative_path: str) -> int:
    return _open_directory_components(
        parent_descriptor=parent_descriptor,
        components=_relative_components(relative_path, allow_dot=True),
    )


def open_regular_file_descriptor(*, root_path: Path, relative_path: str) -> int:
    root_descriptor = open_directory_descriptor(root_path=root_path)
    try:
        return open_regular_file_at_descriptor(
            parent_descriptor=root_descriptor,
            relative_path=relative_path,
        )
    finally:
        os.close(root_descriptor)


def open_regular_file_at_descriptor(
    *, parent_descriptor: int, relative_path: str
) -> int:
    components = _relative_components(relative_path, allow_dot=False)
    parent = _open_directory_components(
        parent_descriptor=parent_descriptor,
        components=components[:-1],
    )
    descriptor: int | None = None
    try:
        descriptor = _open(components[-1], _FILE_OPEN_FLAGS, parent=parent)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise DescriptorPathPolicyError(
                "descriptor path must reference a regular file"
            )
        return descriptor
    except BaseException:
        if descriptor is not None:
            os.close(descriptor)
        raise
    finally:
        os.close(parent)


def _open_trusted_root(root_path: Path) -> int:
    """Open the configured root in one call, then confine everything below it.

    The root comes from trusted configuration (LOCAL_ARTIFACT_ROOT, host-owned
    manifest paths), so symlinks *above* it are the host's own layout - macOS
    `/tmp` -> `/private/tmp`, a relocated Application Support - and the kernel
    resolves those ancestors here. O_NOFOLLOW still applies to the root's own
    final component, so a root swapped for a symlink after it was registered is
    rejected, and every untrusted component below the root is opened with
    O_NOFOLLOW as well.
    """

    _validate_root_path(root_path)
    return _open(str(root_path), _DIRECTORY_OPEN_FLAGS)


def _validate_root_path(root_path: Path) -> None:
    if not root_path.is_absolute() or root_path.anchor != os.sep:
        raise DescriptorPathPolicyError(
            "descriptor root must be an absolute POSIX path"
        )
    if any(
        component in {".", ".."} or "\0" in component for component in root_path.parts
    ):
        raise DescriptorPathPolicyError("descriptor root path is not canonical")


def _replace_directory(descriptor: int, component: str) -> int:
    next_descriptor = _open(component, _DIRECTORY_OPEN_FLAGS, parent=descriptor)
    try:
        os.close(descriptor)
    except BaseException:
        os.close(next_descriptor)
        raise
    return next_descriptor


def _open_directory_components(
    *, parent_descriptor: int, components: tuple[str, ...]
) -> int:
    descriptor = _open(".", _DIRECTORY_OPEN_FLAGS, parent=parent_descriptor)
    try:
        for component in components:
            descriptor = _replace_directory(descriptor, component)
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def _open(component: str, flags: int, *, parent: int | None = None) -> int:
    try:
        if parent is None:
            return os.open(component, flags)
        return os.open(component, flags, dir_fd=parent)
    except FileNotFoundError as exc:
        raise DescriptorPathMissingError("descriptor path does not exist") from exc
    except OSError as exc:
        if exc.errno in {errno.ELOOP, errno.ENOTDIR}:
            raise DescriptorPathPolicyError(
                "descriptor path is not a directory or uses a symlink"
            ) from exc
        raise


def _relative_components(value: str, *, allow_dot: bool) -> tuple[str, ...]:
    if value == ".":
        if allow_dot:
            return ()
        raise DescriptorPathPolicyError("descriptor path must reference a file")
    path = PurePosixPath(value)
    if not value or path.is_absolute() or not path.parts:
        raise DescriptorPathPolicyError("descriptor path must be root-relative")
    if any(
        component in {"", ".", ".."} or "\0" in component for component in path.parts
    ):
        raise DescriptorPathPolicyError("descriptor path contains an unsafe component")
    return path.parts


__all__ = [
    "DescriptorPathError",
    "DescriptorPathMissingError",
    "DescriptorPathPolicyError",
    "open_directory_at_descriptor",
    "open_directory_descriptor",
    "open_regular_file_at_descriptor",
    "open_regular_file_descriptor",
]
