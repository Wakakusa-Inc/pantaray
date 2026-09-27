"""Shared authority for persisted workspace manifest roots."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .workspace_root_authority import validate_workspace_root


@dataclass(frozen=True, slots=True)
class ManifestRoot:
    root_id: str
    manifest_id: str
    source_type: str
    display_name: str
    canonical_real_path: Path
    real_path: Path
    can_read: bool
    can_apply_patch: bool
    can_process_read: bool
    can_process_write: bool


def load_ready_manifest_roots_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    manifest_id: str,
) -> tuple[ManifestRoot, ...]:
    rows = connection.execute(
        """
        SELECT
            wmr.root_id,
            wmr.manifest_id,
            wmr.source_type,
            wmr.display_name,
            wmr.canonical_real_path,
            wmr.real_path,
            wmr.can_read,
            wmr.can_apply_patch,
            wmr.can_process_read,
            wmr.can_process_write
        FROM workspace_manifests AS wm
        JOIN workspace_manifest_roots AS wmr
          ON wmr.manifest_id = wm.manifest_id
        WHERE wm.user_id = ?
          AND wm.manifest_id = ?
          AND wm.status = 'ready'
        ORDER BY LENGTH(wmr.canonical_real_path) DESC,
                 wmr.canonical_real_path ASC
        """,
        (user_id, manifest_id),
    ).fetchall()
    return tuple(_manifest_root_from_row(row) for row in rows)


def load_ready_manifest_root_in_connection(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    manifest_id: str,
    action_id: str,
    root_id: str,
) -> ManifestRoot | None:
    row = connection.execute(
        """
        SELECT
            wmr.root_id,
            wmr.manifest_id,
            wmr.source_type,
            wmr.display_name,
            wmr.canonical_real_path,
            wmr.real_path,
            wmr.can_read,
            wmr.can_apply_patch,
            wmr.can_process_read,
            wmr.can_process_write
        FROM workspace_manifests AS wm
        JOIN workspace_manifest_roots AS wmr
          ON wmr.manifest_id = wm.manifest_id
        WHERE wm.user_id = ?
          AND wm.action_id = ?
          AND wm.manifest_id = ?
          AND wm.status = 'ready'
          AND wmr.root_id = ?
        """,
        (user_id, action_id, manifest_id, root_id),
    ).fetchone()
    return None if row is None else _manifest_root_from_row(row)


def _manifest_root_from_row(row: sqlite3.Row) -> ManifestRoot:
    return ManifestRoot(
        root_id=str(row["root_id"]),
        manifest_id=str(row["manifest_id"]),
        source_type=str(row["source_type"]),
        display_name=str(row["display_name"]),
        canonical_real_path=Path(str(row["canonical_real_path"])),
        real_path=Path(str(row["real_path"])),
        can_read=bool(row["can_read"]),
        can_apply_patch=bool(row["can_apply_patch"]),
        can_process_read=bool(row["can_process_read"]),
        can_process_write=bool(row["can_process_write"]),
    )


def validate_manifest_root_authority(root: ManifestRoot) -> None:
    validate_workspace_root(
        real_path=root.real_path,
        canonical_real_path=root.canonical_real_path,
    )


def path_belongs_to_manifest_root(*, path: Path, root: ManifestRoot) -> bool:
    try:
        path.relative_to(root.canonical_real_path)
    except ValueError:
        return False
    return True


__all__ = [
    "ManifestRoot",
    "load_ready_manifest_root_in_connection",
    "load_ready_manifest_roots_in_connection",
    "path_belongs_to_manifest_root",
    "validate_manifest_root_authority",
]
