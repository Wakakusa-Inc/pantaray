from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import cast

import pytest

from pantaray_agents.local_runtime.storage.migrations.connection import (
    configure_connection,
)
from pantaray_agents.local_runtime.storage.transactions import (
    SQLiteTransactionOwnershipError,
    immediate_transaction,
)
from pantaray_agents.local_runtime.tooling.action_subagent_resource_authority import (
    ActionSubagentResourceActorError,
    ActionSubagentResourceWriteDeniedError,
    AuthorizedClaimActor,
    authorize_action_subagent_resource_writes,
    resolve_action_subagent_command_write_roots,
)
from pantaray_agents.local_runtime.tooling.action_subagent_resource_claims import (
    ActionSubagentResourceClaim,
    ActionSubagentResourceClaimConflictError,
    ExternalResourceClaim,
    WorkspacePathResourceClaim,
    acquire_action_subagent_resource_claims_in_connection,
)
from pantaray_agents.local_runtime.tooling.action_subagent_resource_identity import (
    ActionSubagentResourceIdentityError,
    ExternalResourceIdentity,
    WorkspaceResourceIdentity,
    normalize_workspace_resource_key,
)
from pantaray_agents.local_runtime.tooling.models import ActionExecutionContext

from .resource_recovery_test_support import bootstrap_runtime_db

BUSY_TIMEOUT_MS = 1_000
ACQUIRED_AT = "2026-09-01T00:01:00Z"


def _runtime(tmp_path: Path) -> tuple[Path, ActionExecutionContext]:
    db_path, raw_context = bootstrap_runtime_db(tmp_path)
    context = cast(ActionExecutionContext, raw_context)
    with _connect(db_path) as connection:
        with connection:
            _insert_process(connection, "parent-1", kind="action")
            for child_id in ("child-1", "child-2"):
                _insert_process(
                    connection,
                    child_id,
                    kind="action_subagent",
                    parent_process_id="parent-1",
                )
    return db_path, context


def _connect(db_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(db_path)
    configure_connection(connection, BUSY_TIMEOUT_MS)
    connection.row_factory = sqlite3.Row
    return connection


def _insert_process(
    connection: sqlite3.Connection,
    process_id: str,
    *,
    kind: str,
    parent_process_id: str | None = None,
) -> None:
    connection.execute(
        """
        INSERT INTO processes(
            process_id, user_id, kind, status, action_id, started_at,
            updated_at, heartbeat_at, next_event_seq, parent_process_id
        ) VALUES (?, 'user-1', ?, 'running', 'action-1', ?, ?, ?, 1, ?)
        """,
        (process_id, kind, ACQUIRED_AT, ACQUIRED_AT, ACQUIRED_AT, parent_process_id),
    )


def _acquire(
    connection: sqlite3.Connection,
    *,
    child_process_id: str,
    claims: tuple[ActionSubagentResourceClaim, ...],
) -> None:
    with immediate_transaction(connection):
        _acquire_in_connection(connection, child_process_id, claims)


def _acquire_in_connection(
    connection: sqlite3.Connection,
    child_process_id: str,
    claims: tuple[ActionSubagentResourceClaim, ...],
) -> None:
    acquire_action_subagent_resource_claims_in_connection(
        connection,
        user_id="user-1",
        action_id="action-1",
        parent_process_id="parent-1",
        child_process_id=child_process_id,
        acquired_at=ACQUIRED_AT,
        claims=claims,
    )


def _workspace_claim(
    context: ActionExecutionContext,
    claim_id: str,
    raw_path: str,
    *,
    current_cwd: Path | None = None,
) -> WorkspacePathResourceClaim:
    return WorkspacePathResourceClaim(
        claim_id=claim_id,
        manifest_id=context.manifest_id,
        raw_path=raw_path,
        current_cwd=current_cwd or context.workspace_path,
    )


def _workspace_resource(
    context: ActionExecutionContext, raw_path: str
) -> WorkspaceResourceIdentity:
    return WorkspaceResourceIdentity.from_resolved_path(
        manifest_id=context.manifest_id,
        resolved_path=(context.workspace_path / raw_path).resolve(),
    )


def _authorize(
    db_path: Path,
    *,
    actor_process_id: str,
    resources: tuple[WorkspaceResourceIdentity | ExternalResourceIdentity, ...],
) -> AuthorizedClaimActor:
    return authorize_action_subagent_resource_writes(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        action_id="action-1",
        actor_process_id=actor_process_id,
        resources=resources,
    )


def test_workspace_claims_use_physical_path_overlap_and_ignore_released_rows(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    nested = context.workspace_path / "nested"
    nested.mkdir()
    with _connect(db_path) as connection:
        connection.execute(
            """
            INSERT INTO workspace_manifest_roots(
                root_id, manifest_id, source_type, source_id, display_name,
                canonical_real_path, real_path, can_read, can_apply_patch,
                can_process_read, can_process_write, created_at
            ) VALUES (
                'root:nested', ?, 'folder', 'folder:nested', 'nested',
                ?, ?, 1, 1, 1, 1, ?
            )
            """,
            (context.manifest_id, str(nested.resolve()), str(nested), ACQUIRED_AT),
        )
        connection.commit()

        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-src", "Src", current_cwd=nested),),
        )
        for index, (raw_path, cwd) in enumerate(
            (
                ("src", nested),
                ("src/file", nested),
                ("SRC/file", nested),
                (".", context.workspace_path),
            )
        ):
            with pytest.raises(ActionSubagentResourceClaimConflictError):
                _acquire(
                    connection,
                    child_process_id="child-2",
                    claims=(
                        _workspace_claim(
                            context, f"conflict-{index}", raw_path, current_cwd=cwd
                        ),
                    ),
                )

        _acquire(
            connection,
            child_process_id="child-2",
            claims=(
                _workspace_claim(context, "claim-src2", "src2", current_cwd=nested),
            ),
        )
        with immediate_transaction(connection):
            connection.execute(
                "UPDATE action_subagent_resource_claims SET released_at = ? "
                "WHERE claim_id = 'claim-src'",
                ("2026-09-01T00:02:00Z",),
            )
        _acquire(
            connection,
            child_process_id="child-2",
            claims=(
                _workspace_claim(
                    context, "claim-src-reused", "src", current_cwd=nested
                ),
            ),
        )
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-unicode", "Café"),),
        )
        with pytest.raises(ActionSubagentResourceClaimConflictError):
            _acquire(
                connection,
                child_process_id="child-2",
                claims=(
                    _workspace_claim(context, "conflict-unicode", "Cafe\u0301/file"),
                ),
            )

        stored = connection.execute(
            "SELECT root_identity, normalized_key FROM action_subagent_resource_claims "
            "WHERE claim_id = 'claim-src'"
        ).fetchone()

    assert tuple(stored) == (
        context.manifest_id,
        normalize_workspace_resource_key((nested / "Src").resolve()),
    )


def test_external_claims_conflict_only_on_the_exact_preserved_pair(
    tmp_path: Path,
) -> None:
    db_path, _ = _runtime(tmp_path)
    original = ExternalResourceClaim("external-1", " authority ", " Item/1 ")
    with _connect(db_path) as connection:
        _acquire(connection, child_process_id="child-1", claims=(original,))
        with pytest.raises(ActionSubagentResourceClaimConflictError):
            _acquire(
                connection,
                child_process_id="child-2",
                claims=(
                    ExternalResourceClaim(
                        "external-duplicate", " authority ", " Item/1 "
                    ),
                ),
            )
        _acquire(
            connection,
            child_process_id="child-2",
            claims=(
                ExternalResourceClaim("external-namespace", "Authority", " Item/1 "),
                ExternalResourceClaim("external-key", " authority ", " item/1 "),
            ),
        )
        with pytest.raises(ValueError, match="must not be blank"):
            _acquire(
                connection,
                child_process_id="child-2",
                claims=(ExternalResourceClaim("external-blank", " ", "key"),),
            )
        stored = connection.execute(
            "SELECT root_identity, normalized_key FROM action_subagent_resource_claims "
            "WHERE claim_id = 'external-1'"
        ).fetchone()

    assert tuple(stored) == (" authority ", " Item/1 ")


def test_transaction_ownership_precedes_resolution_and_caller_rollback_is_atomic(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    with _connect(db_path) as connection:
        with pytest.raises(SQLiteTransactionOwnershipError):
            _acquire_in_connection(
                connection,
                "child-1",
                (
                    WorkspacePathResourceClaim(
                        "outside-transaction", "missing-manifest", "outside", tmp_path
                    ),
                ),
            )
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-blocked", "blocked"),),
        )

        with pytest.raises(ActionSubagentResourceClaimConflictError):
            with immediate_transaction(connection):
                _insert_process(
                    connection,
                    "child-rollback",
                    kind="action_subagent",
                    parent_process_id="parent-1",
                )
                _acquire_in_connection(
                    connection,
                    "child-rollback",
                    (
                        _workspace_claim(context, "claim-partial", "safe"),
                        _workspace_claim(context, "claim-conflict", "blocked/child"),
                    ),
                )

        partial_count = connection.execute(
            "SELECT COUNT(*) FROM action_subagent_resource_claims "
            "WHERE claim_id IN ('outside-transaction', 'claim-partial')"
        ).fetchone()
        child_count = connection.execute(
            "SELECT COUNT(*) FROM processes WHERE process_id = 'child-rollback'"
        ).fetchone()

    assert tuple(partial_count) == (0,)
    assert tuple(child_count) == (0,)


def test_precise_write_authority_tracks_active_parent_child_ownership(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    claimed = _workspace_resource(context, "claimed")
    nested = _workspace_resource(context, "claimed/nested")
    case_variant = _workspace_resource(context, "Claimed/nested")
    outside = _workspace_resource(context, "outside")
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )

    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _authorize(
            db_path,
            actor_process_id="parent-1",
            resources=(outside, nested),
        )
    parent = _authorize(db_path, actor_process_id="parent-1", resources=(outside,))
    child = _authorize(
        db_path,
        actor_process_id="child-1",
        resources=(claimed, nested),
    )
    assert (parent.role, parent.parent_process_id) == ("parent", "parent-1")
    assert (child.role, child.parent_process_id) == ("child", "parent-1")

    for actor_process_id, resource in (
        ("child-1", outside),
        ("child-1", case_variant),
        ("child-2", claimed),
    ):
        with pytest.raises(ActionSubagentResourceWriteDeniedError):
            _authorize(
                db_path,
                actor_process_id=actor_process_id,
                resources=(resource,),
            )

    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE action_subagent_resource_claims SET released_at = ? "
            "WHERE claim_id = 'claim-1'",
            ("2026-09-01T00:03:00Z",),
        )
        connection.commit()
    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _authorize(db_path, actor_process_id="child-1", resources=(nested,))


def test_double_slash_alias_cannot_bypass_parent_claim_overlap(tmp_path: Path) -> None:
    db_path, context = _runtime(tmp_path)
    claimed = _workspace_resource(context, "claimed")
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )

    with pytest.raises(ActionSubagentResourceIdentityError):
        _authorize(
            db_path,
            actor_process_id="parent-1",
            resources=(
                WorkspaceResourceIdentity(
                    context.manifest_id,
                    f"/{claimed.normalized_key}",
                ),
            ),
        )


def test_external_write_authority_uses_the_exact_preserved_pair(tmp_path: Path) -> None:
    db_path, _ = _runtime(tmp_path)
    claimed = ExternalResourceIdentity(" authority ", " Item/1 ")
    different = ExternalResourceIdentity(" authority ", " item/1 ")
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(ExternalResourceClaim("external-1", " authority ", " Item/1 "),),
        )

    with pytest.raises(ActionSubagentResourceWriteDeniedError):
        _authorize(db_path, actor_process_id="parent-1", resources=(claimed,))
    _authorize(db_path, actor_process_id="parent-1", resources=(different,))
    _authorize(db_path, actor_process_id="child-1", resources=(claimed,))
    for actor_process_id, resource in (
        ("child-1", different),
        ("child-2", claimed),
    ):
        with pytest.raises(ActionSubagentResourceWriteDeniedError):
            _authorize(
                db_path,
                actor_process_id=actor_process_id,
                resources=(resource,),
            )


def test_command_roots_deny_parent_overlap_and_intersect_child_claims(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    workspace = _workspace_resource(context, ".")
    claimed = _workspace_resource(context, "claimed")
    nested = _workspace_resource(context, "claimed/nested")
    case_variant = _workspace_resource(context, "Claimed/nested")
    outside = _workspace_resource(context, "outside")
    with _connect(db_path) as connection:
        _acquire(
            connection,
            child_process_id="child-1",
            claims=(_workspace_claim(context, "claim-1", "claimed"),),
        )

    assert resolve_action_subagent_command_write_roots(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        action_id="action-1",
        actor_process_id="parent-1",
        candidate_roots=(workspace, outside),
    ) == (outside,)
    assert resolve_action_subagent_command_write_roots(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        action_id="action-1",
        actor_process_id="parent-1",
        candidate_roots=(outside,),
    ) == (outside,)
    assert resolve_action_subagent_command_write_roots(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id="user-1",
        action_id="action-1",
        actor_process_id="child-1",
        candidate_roots=(workspace, nested, case_variant, workspace),
    ) == (claimed, nested)
    assert (
        resolve_action_subagent_command_write_roots(
            db_path=db_path,
            busy_timeout_ms=BUSY_TIMEOUT_MS,
            user_id="user-1",
            action_id="action-1",
            actor_process_id="child-2",
            candidate_roots=(workspace,),
        )
        == ()
    )


def test_actor_authority_fails_closed_for_invalid_runtime_lineage(
    tmp_path: Path,
) -> None:
    db_path, context = _runtime(tmp_path)
    resource = _workspace_resource(context, "outside")
    for actor_process_id, user_id, action_id in (
        ("missing", "user-1", "action-1"),
        ("child-1", "other-user", "action-1"),
        ("child-1", "user-1", "other-action"),
    ):
        with pytest.raises(ActionSubagentResourceActorError):
            authorize_action_subagent_resource_writes(
                db_path=db_path,
                busy_timeout_ms=BUSY_TIMEOUT_MS,
                user_id=user_id,
                action_id=action_id,
                actor_process_id=actor_process_id,
                resources=(resource,),
            )

    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE processes SET status = 'completed' WHERE process_id = 'child-1'"
        )
        connection.commit()
    with pytest.raises(ActionSubagentResourceActorError):
        _authorize(db_path, actor_process_id="child-1", resources=(resource,))
    with _connect(db_path) as connection:
        connection.execute(
            "UPDATE processes SET status = 'completed' WHERE process_id = 'parent-1'"
        )
        connection.commit()
    with pytest.raises(ActionSubagentResourceActorError):
        _authorize(db_path, actor_process_id="child-2", resources=(resource,))
    with pytest.raises(ActionSubagentResourceIdentityError):
        WorkspaceResourceIdentity("manifest-1", "/workspace/claimed/../outside")
