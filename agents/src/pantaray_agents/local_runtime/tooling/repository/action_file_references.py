from __future__ import annotations

import sqlite3
from pathlib import Path

from ...storage.migrations import MigrationError
from ..models import (
    TOOL_INVOCATION_TERMINAL_STATUSES,
    ToolInvocationFileReferenceInput,
)
from ..workspace_manifest_roots import (
    ManifestRoot,
    load_ready_manifest_roots_in_connection,
    path_belongs_to_manifest_root,
    validate_manifest_root_authority,
)
from ..workspace_root_authority import (
    WorkspaceRootAuthorityError,
)


def _record_tool_invocation_file_references_in_connection(
    *,
    connection: sqlite3.Connection,
    invocation_id: str,
    file_references: tuple[ToolInvocationFileReferenceInput, ...],
) -> None:
    terminal_placeholders = ", ".join("?" for _ in TOOL_INVOCATION_TERMINAL_STATUSES)
    invocation = connection.execute(
        f"""
        SELECT
            ti.user_id,
            ti.action_id,
            ti.manifest_id,
            es.cwd_path
        FROM tool_invocations AS ti
        JOIN execution_sessions AS es
          ON es.execution_session_id = ti.execution_session_id
        JOIN workspace_manifests AS wm
          ON wm.manifest_id = ti.manifest_id
         AND wm.user_id = ti.user_id
         AND wm.action_id = ti.action_id
         AND wm.status = 'ready'
        WHERE ti.invocation_id = ?
          AND ti.status IN ({terminal_placeholders})
        """,
        (invocation_id, *TOOL_INVOCATION_TERMINAL_STATUSES),
    ).fetchone()
    if invocation is None:
        raise MigrationError(
            "terminal tool invocation with ready manifest not found for file reference: "
            f"{invocation_id}"
        )
    user_id = str(invocation["user_id"])
    action_id = str(invocation["action_id"])
    manifest_id = str(invocation["manifest_id"])
    roots = load_ready_manifest_roots_in_connection(
        connection=connection,
        user_id=user_id,
        manifest_id=manifest_id,
    )

    insert_values: list[tuple[str, ...]] = []
    validated_root_ids: set[str] = set()
    for file_reference in file_references:
        target_path = _target_path_for_reference(
            cwd_path=Path(str(invocation["cwd_path"])),
            value=file_reference.path,
        )
        root = _find_root_for_target(roots=roots, target_path=target_path)
        if root is None:
            raise MigrationError(
                f"file reference path is outside manifest roots: {target_path}"
            )
        if root.root_id not in validated_root_ids:
            _validate_root(root)
            validated_root_ids.add(root.root_id)
        canonical_path = target_path.resolve(strict=False)
        insert_values.append(
            (
                file_reference.file_reference_id,
                user_id,
                action_id,
                manifest_id,
                root.root_id,
                invocation_id,
                str(target_path),
                str(canonical_path),
            )
        )
    connection.executemany(
        """
                INSERT INTO file_references(
                    file_reference_id,
                    user_id,
                    action_id,
                    manifest_id,
                    root_id,
                    tool_invocation_id,
                    local_path,
                    canonical_local_path,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(action_id, manifest_id, canonical_local_path) DO NOTHING
                """,
        insert_values,
    )


def _target_path_for_reference(*, cwd_path: Path, value: str) -> Path:
    stripped = value.strip()
    if not stripped:
        raise MigrationError("file reference path must not be empty")
    if stripped.startswith("~"):
        raise MigrationError("file reference path must not use shell home expansion")
    path = Path(stripped)
    return (path if path.is_absolute() else cwd_path / path).resolve(strict=False)


def _find_root_for_target(
    *,
    roots: tuple[ManifestRoot, ...],
    target_path: Path,
) -> ManifestRoot | None:
    canonical_target = target_path.resolve(strict=False)
    matches = tuple(
        root
        for root in roots
        if path_belongs_to_manifest_root(path=canonical_target, root=root)
    )
    return _most_specific_root(matches)


def _most_specific_root(roots: tuple[ManifestRoot, ...]) -> ManifestRoot | None:
    if not roots:
        return None
    return max(roots, key=lambda root: len(root.canonical_real_path.parts))


def _validate_root(root: ManifestRoot) -> None:
    try:
        validate_manifest_root_authority(root)
    except WorkspaceRootAuthorityError as exc:
        raise MigrationError(str(exc)) from exc


__all__ = ["_record_tool_invocation_file_references_in_connection"]
