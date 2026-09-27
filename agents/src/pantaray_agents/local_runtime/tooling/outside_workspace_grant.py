"""Folders outside the workspace that the user allowed for one conversation.

"Allow for this conversation" on an outside-workspace approval makes the
approved folder a writable root of that Action's workspace manifest. Later calls
of the Action resolve inside it like a registered folder and follow the normal
approval mode; other Actions never see it.
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from pantaray_agents.local_runtime.runtime.runtime_env import (
    read_local_runtime_artifact_root,
)
from pantaray_agents.schema.agent.base import JSONValue

from .repository.manifests import insert_approved_folder_root_in_connection
from .workspace_manifest_roots import ManifestRoot
from .workspace_root_authority import (
    WorkspaceRootAuthorityError,
    validate_workspace_root,
)

APPROVED_FOLDER_SOURCE_TYPE = "approved_folder"


class OutsideWorkspaceGrantError(ValueError):
    """The approval cannot open its folder for the rest of the conversation."""


def app_owned_roots(db_path: Path) -> tuple[Path, ...]:
    return (
        read_local_runtime_artifact_root().resolve(),
        db_path.parent.resolve(),
    )


def path_is_within(*, path: Path, root: Path) -> bool:
    if path.is_relative_to(root):
        return True
    # APFS case/Unicode aliases need directory identity, not lexical comparison.
    for candidate in (path, *path.parents):
        try:
            if candidate.samefile(root):
                return True
        except OSError:
            continue
    return False


def folder_can_be_granted(*, folder: Path, db_path: Path) -> bool:
    """Whether commands may write anywhere under this folder.

    A folder that is not an existing canonical directory, or that lies inside
    or encloses app-owned storage (/, the home folder, ~/Library...), is refused.
    """

    try:
        validate_workspace_root(real_path=folder, canonical_real_path=folder)
    except WorkspaceRootAuthorityError:
        return False
    return not any(
        path_is_within(path=folder, root=root) or path_is_within(path=root, root=folder)
        for root in app_owned_roots(db_path)
    )


def approved_summary_covers_request(
    *,
    approved: dict[str, JSONValue],
    requested: dict[str, JSONValue],
    manifest_roots: tuple[ManifestRoot, ...],
) -> bool:
    """Whether a stored approval summary still describes this tool request."""

    if approved == requested:
        return True
    # After "Allow for this conversation" the approved call resolves inside the
    # newly granted root, so its summary no longer names an outside folder. A
    # later registration of the same folder replaces that root with a folder root
    # at the next reconcile, which still covers the approved call.
    outside = approved.get("outside_workspace")
    if not isinstance(outside, dict):
        return False
    remainder = {
        key: value for key, value in approved.items() if key != "outside_workspace"
    }
    return remainder == requested and any(
        root.source_type in {APPROVED_FOLDER_SOURCE_TYPE, "folder"}
        and str(root.canonical_real_path) == outside.get("folder_path")
        for root in manifest_roots
    )


def grant_outside_workspace_folder_in_connection(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    approval_session_id: str,
    db_path: Path,
    granted_at: str,
) -> None:
    """Add the approval's folder as a writable root of the Action's manifest.

    The folder comes from the stored approval summary, never from the client.
    """

    row = connection.execute(
        """
        SELECT manifest.manifest_id, approval.command_summary_json
        FROM approval_sessions AS approval
        JOIN workspace_manifests AS manifest
          ON manifest.manifest_id = approval.manifest_id
         AND manifest.user_id = approval.user_id
         AND manifest.action_id = approval.action_id
         AND manifest.status = 'ready'
        WHERE approval.approval_session_id = ?
          AND approval.user_id = ?
          AND approval.action_id = ?
        """,
        (approval_session_id, user_id, action_id),
    ).fetchone()
    if row is None:
        raise OutsideWorkspaceGrantError("approval has no ready workspace manifest")
    outside = json.loads(str(row[1])).get("outside_workspace")
    folder_path = outside.get("folder_path") if isinstance(outside, dict) else None
    if not isinstance(folder_path, str):
        raise OutsideWorkspaceGrantError(
            "approval does not open a folder outside the workspace"
        )
    folder = Path(folder_path)
    if not folder_can_be_granted(folder=folder, db_path=db_path):
        raise OutsideWorkspaceGrantError(
            "folder cannot be allowed for the whole conversation"
        )
    insert_approved_folder_root_in_connection(
        connection,
        manifest_id=str(row[0]),
        approval_session_id=approval_session_id,
        folder=folder,
        created_at=granted_at,
    )


__all__ = [
    "APPROVED_FOLDER_SOURCE_TYPE",
    "OutsideWorkspaceGrantError",
    "app_owned_roots",
    "approved_summary_covers_request",
    "folder_can_be_granted",
    "grant_outside_workspace_folder_in_connection",
    "path_is_within",
]
