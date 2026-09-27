from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.memory_catalog.repository import (
    load_latest_active_node_by_source,
    load_revision,
)


class LocalFactIdentityError(RuntimeError):
    """Stored Fact identity violates the unified Memory run's start contract."""


def load_current_fact_identity(
    *, connection: sqlite3.Connection, user_id: str
) -> tuple[str, str] | None:
    """The active Fact node's ``(fact_id, created_at)``, or None when it has none.

    None means the user has no Fact yet, so the caller owns the identity the
    first Fact will get.
    """

    node = load_latest_active_node_by_source(
        connection=connection,
        user_id=user_id,
        source="fact",
    )
    if node is None:
        projection = connection.execute(
            """
            SELECT 1
            FROM agent_facts
            WHERE user_id = ? AND status = 'success'
            LIMIT 1
            """,
            (user_id,),
        ).fetchone()
        if projection is not None:
            raise LocalFactIdentityError(
                "Successful Fact projection has no active memory node"
            )
        return None

    if node.integrity != "healthy" or node.current_revision_id is None:
        raise LocalFactIdentityError(
            "Active Fact memory node has no healthy current revision"
        )
    revision = load_revision(
        connection=connection,
        user_id=user_id,
        revision_id=node.current_revision_id,
    )
    if (
        revision is None
        or revision.node_id != node.node_id
        or revision.body_kind != "artifact_tree"
    ):
        raise LocalFactIdentityError(
            "Active Fact memory revision does not match its artifact node"
        )
    projection = connection.execute(
        """
        SELECT fact_id, structured_fact_sha256, created_at
        FROM agent_facts
        WHERE user_id = ? AND fact_id = ? AND status = 'success'
        LIMIT 1
        """,
        (user_id, node.source_record_id),
    ).fetchone()
    if projection is None:
        raise LocalFactIdentityError(
            "Active Fact memory node has no successful projection"
        )
    fact_id = str(projection["fact_id"] or "").strip()
    fact_sha256 = str(projection["structured_fact_sha256"] or "").strip()
    fact_created_at = str(projection["created_at"] or "").strip()
    if not fact_id or not fact_created_at or fact_sha256 != revision.content_sha256:
        raise LocalFactIdentityError(
            "Active Fact projection does not match its current revision"
        )
    return fact_id, fact_created_at
