from __future__ import annotations

import os
from pathlib import Path

from .errors import MemoryCatalogIntegrityError


def fsync_artifact_tree(*, tree_root: Path, ancestor_root: Path) -> None:
    """Synchronize one artifact tree and its ancestor directory entries."""
    resolved_tree_root = tree_root.resolve()
    resolved_ancestor_root = ancestor_root.resolve()
    if (
        resolved_tree_root == resolved_ancestor_root
        or resolved_ancestor_root not in resolved_tree_root.parents
    ):
        raise MemoryCatalogIntegrityError(
            "artifact tree must be contained by its durability root"
        )
    if tree_root.is_symlink() or not resolved_tree_root.is_dir():
        raise MemoryCatalogIntegrityError("artifact tree root is absent or unsafe")

    directories = [
        Path(current_root)
        for current_root, _directory_names, _file_names in os.walk(
            resolved_tree_root,
            topdown=False,
            followlinks=False,
        )
    ]
    current = resolved_tree_root.parent
    while True:
        directories.append(current)
        if current == resolved_ancestor_root:
            break
        current = current.parent

    for directory in directories:
        _fsync_directory(directory)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(
        path,
        os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


__all__ = ["fsync_artifact_tree"]
