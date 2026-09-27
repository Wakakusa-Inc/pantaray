from __future__ import annotations

import sqlite3
from pathlib import Path

from .action_subagent_resource_identity import (
    CanonicalResourceIdentity,
    WorkspaceResourceIdentity,
    resource_identities_overlap,
)
from .models import CommandToolInvocationStartInput


def load_other_actor_command_write_roots(
    connection: sqlite3.Connection,
    *,
    user_id: str,
    action_id: str,
    actor_process_id: str,
) -> tuple[Path, ...]:
    rows = connection.execute(
        """
        SELECT DISTINCT grant_row.normalized_key
        FROM command_workspace_write_grants AS grant_row
        JOIN tool_invocations AS invocation
          ON invocation.invocation_id = grant_row.invocation_id
        WHERE invocation.user_id = ? AND invocation.action_id = ?
          AND grant_row.actor_process_id != ?
          AND (
            invocation.status IN ('queued', 'running')
            OR EXISTS (
                SELECT 1 FROM tool_runtime_resources AS resource
                WHERE resource.tool_invocation_id = invocation.invocation_id
                  AND resource.resource_kind = 'process_group'
                  AND resource.status != 'cleaned'
            )
          )
        """,
        (user_id, action_id, actor_process_id),
    ).fetchall()
    return tuple(Path(row[0]) for row in rows)


def resource_overlaps_command_write_roots(
    resource: CanonicalResourceIdentity, write_roots: tuple[Path, ...]
) -> bool:
    if not isinstance(resource, WorkspaceResourceIdentity):
        return False
    # OS write grants remain physical until cleanup, even across manifest changes.
    return any(
        resource_identities_overlap(
            resource,
            WorkspaceResourceIdentity.from_resolved_path(
                manifest_id=resource.manifest_id, resolved_path=root
            ),
        )
        for root in write_roots
    )


def insert_command_write_grants(
    connection: sqlite3.Connection, invocation: CommandToolInvocationStartInput
) -> None:
    connection.executemany(
        """
        INSERT INTO command_workspace_write_grants(
            invocation_id, actor_process_id, normalized_key
        ) VALUES (?, ?, ?)
        """,
        (
            (invocation.invocation_id, invocation.actor_process_id, str(root))
            for root in invocation.write_roots
        ),
    )
