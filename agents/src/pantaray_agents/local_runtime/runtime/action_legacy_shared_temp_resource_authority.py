from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import NamedTuple

from ..storage.migrations import MigrationError
from ..tooling.locks.workspace_lock import workspace_lock_store_path
from ..tooling.models import StoredToolRuntimeResource
from ..tooling.resources.resource_db_support import build_tool_runtime_resource
from .action_legacy_shared_temp_core_authority import (
    LegacyActionSharedTempCoreAuthority,
    list_legacy_action_shared_temp_core_authorities_in_connection,
)


class LegacyInvocationEvidence(NamedTuple):
    invocation_id: str
    user_id: str
    action_id: str
    step_id: str | None
    tool_id: str
    manifest_id: str
    execution_session_id: str
    intent_class: str
    tool_request_id: str | None
    status: str
    completed_at: str | None


class LegacyActionSharedTempResourceAuthority(NamedTuple):
    core: LegacyActionSharedTempCoreAuthority
    invocations: tuple[LegacyInvocationEvidence, ...]
    resources: tuple[StoredToolRuntimeResource, ...]


class LegacyActionSharedTempPrecleanupAuthority(NamedTuple):
    core: LegacyActionSharedTempCoreAuthority
    resources: tuple[StoredToolRuntimeResource, ...]


class _LegacyActionSharedTempInventory(NamedTuple):
    core: LegacyActionSharedTempCoreAuthority
    invocations: tuple[LegacyInvocationEvidence, ...]
    resources: tuple[StoredToolRuntimeResource, ...]
    blockers: tuple[StoredToolRuntimeResource, ...]


def list_legacy_action_shared_temp_precleanup_authorities_in_connection(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[LegacyActionSharedTempPrecleanupAuthority, ...]:
    return tuple(
        LegacyActionSharedTempPrecleanupAuthority(row.core, row.blockers)
        for row in _list_inventories(
            connection=connection, resolved_db_path=resolved_db_path
        )
    )


def list_legacy_action_shared_temp_resource_authorities_in_connection(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[LegacyActionSharedTempResourceAuthority, ...]:
    inventories = _list_inventories(
        connection=connection, resolved_db_path=resolved_db_path
    )
    if any(row.blockers for row in inventories):
        raise MigrationError("legacy Action external resources require cleanup")
    return tuple(
        LegacyActionSharedTempResourceAuthority(
            row.core, row.invocations, row.resources
        )
        for row in inventories
    )


def _list_inventories(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[_LegacyActionSharedTempInventory, ...]:
    cores = list_legacy_action_shared_temp_core_authorities_in_connection(
        connection=connection, resolved_db_path=resolved_db_path
    )
    results: list[_LegacyActionSharedTempInventory] = []
    lock_store = workspace_lock_store_path(db_path=resolved_db_path)
    for core in cores:
        invocations = _load_invocations(connection, core=core)
        resources = _load_resources(connection, core=core, invocations=invocations)
        _require_session_roots(core=core, resources=resources)
        blockers = tuple(
            resource
            for resource in resources
            if _requires_precleanup(
                resource, fixed_root=core.fixed_root_path, lock_store=lock_store
            )
        )
        results.append(
            _LegacyActionSharedTempInventory(core, invocations, resources, blockers)
        )
    return tuple(results)


def _load_invocations(
    connection: sqlite3.Connection, *, core: LegacyActionSharedTempCoreAuthority
) -> tuple[LegacyInvocationEvidence, ...]:
    session_ids = tuple(session.execution_session_id for session in core.sessions)
    placeholders = ",".join("?" for _ in session_ids)
    rows = connection.execute(
        f"""SELECT invocation.invocation_id,invocation.user_id,invocation.action_id,
                   invocation.step_id,invocation.tool_id,invocation.manifest_id,
                   invocation.execution_session_id,invocation.intent_class,
                   invocation.tool_request_id,invocation.status,
                   invocation.completed_at,step.user_id AS step_user_id,
                   step.action_id AS step_action_id
            FROM tool_invocations AS invocation
            LEFT JOIN agent_action_steps AS step ON step.step_id=invocation.step_id
            WHERE invocation.action_id=?
               OR invocation.execution_session_id IN ({placeholders})
               OR invocation.manifest_id=? OR step.action_id=?
            ORDER BY invocation.invocation_id""",
        (core.action_id, *session_ids, core.manifest.manifest_id, core.action_id),
    ).fetchall()
    evidence: list[LegacyInvocationEvidence] = []
    for row in rows:
        invocation = LegacyInvocationEvidence(
            invocation_id=_text(row["invocation_id"]),
            user_id=_text(row["user_id"]),
            action_id=_text(row["action_id"]),
            step_id=_optional_text(row["step_id"]),
            tool_id=_text(row["tool_id"]),
            manifest_id=_text(row["manifest_id"]),
            execution_session_id=_text(row["execution_session_id"]),
            intent_class=_text(row["intent_class"]),
            tool_request_id=_optional_text(row["tool_request_id"]),
            status=_text(row["status"]),
            completed_at=_optional_text(row["completed_at"]),
        )
        if (
            invocation.user_id != core.user_id
            or invocation.action_id != core.action_id
            or invocation.manifest_id != core.manifest.manifest_id
            or invocation.execution_session_id not in session_ids
            or (
                invocation.step_id is not None
                and (
                    row["step_user_id"] != core.user_id
                    or row["step_action_id"] != core.action_id
                )
            )
        ):
            raise MigrationError("legacy Action invocation authority is inconsistent")
        evidence.append(invocation)
    return tuple(evidence)


def _load_resources(
    connection: sqlite3.Connection,
    *,
    core: LegacyActionSharedTempCoreAuthority,
    invocations: tuple[LegacyInvocationEvidence, ...],
) -> tuple[StoredToolRuntimeResource, ...]:
    session_ids = tuple(session.execution_session_id for session in core.sessions)
    invocation_ids = tuple(invocation.invocation_id for invocation in invocations)
    clauses = ["action_id=?", f"execution_session_id IN ({_marks(session_ids)})"]
    parameters: tuple[object, ...] = (core.action_id, *session_ids)
    if invocation_ids:
        clauses.append(f"tool_invocation_id IN ({_marks(invocation_ids)})")
        parameters += invocation_ids
    rows = connection.execute(
        f"""SELECT resource_id,execution_session_id,tool_invocation_id,action_id,
                   resource_kind,status,pid,pgid,process_start_signature,resource_path,
                   created_at,updated_at,cleaned_at,cleanup_error,cleanup_attempts,lock_id
            FROM tool_runtime_resources WHERE {" OR ".join(clauses)}
            ORDER BY resource_id""",
        parameters,
    ).fetchall()
    invocation_by_id = {row.invocation_id: row for row in invocations}
    resources: list[StoredToolRuntimeResource] = []
    for row in rows:
        resource = _resource_evidence(row)
        invocation = (
            invocation_by_id.get(resource.tool_invocation_id)
            if resource.tool_invocation_id is not None
            else None
        )
        if (
            resource.action_id != core.action_id
            or resource.execution_session_id not in session_ids
            or (
                resource.tool_invocation_id is not None
                and (
                    invocation is None
                    or invocation.execution_session_id != resource.execution_session_id
                )
            )
        ):
            raise MigrationError("legacy Action resource authority is inconsistent")
        resources.append(resource)
    return tuple(resources)


def _resource_evidence(row: sqlite3.Row) -> StoredToolRuntimeResource:
    stored = build_tool_runtime_resource(row)
    if (
        stored.action_id is None
        or not stored.resource_id.strip()
        or not stored.updated_at.strip()
        or stored.cleanup_attempts < 0
    ):
        raise MigrationError("legacy Action resource evidence is incomplete")
    return stored


def _require_session_roots(
    *,
    core: LegacyActionSharedTempCoreAuthority,
    resources: tuple[StoredToolRuntimeResource, ...],
) -> None:
    for session in core.sessions:
        roots = tuple(
            resource
            for resource in resources
            if resource.execution_session_id == session.execution_session_id
            and resource.resource_kind == "temp_dir"
            and resource.tool_invocation_id is None
        )
        if (
            len(roots) != 1
            or roots[0].resource_path != str(core.fixed_root_path)
            or any(
                value is not None
                for value in (
                    roots[0].pid,
                    roots[0].pgid,
                    roots[0].process_start_signature,
                    roots[0].lock_id,
                )
            )
        ):
            raise MigrationError("legacy Action session root authority is inconsistent")


def _requires_precleanup(
    resource: StoredToolRuntimeResource, *, fixed_root: Path, lock_store: Path
) -> bool:
    if resource.status == "cleaned":
        return False
    if resource.resource_kind == "process_group":
        if (
            resource.status not in {"active", "cleanup_failed"}
            or resource.resource_path is not None
            or resource.lock_id is not None
        ):
            raise MigrationError("legacy Action process-group cleanup is not retryable")
        return True
    path = _normalized_absolute_path(resource.resource_path)
    if path is not None and (path == fixed_root or fixed_root in path.parents):
        return False
    if (
        resource.resource_kind == "lock"
        and resource.status in {"active", "cleanup_failed"}
        and resource.tool_invocation_id is not None
        and resource.lock_id is not None
        and path is not None
        and path.parent == lock_store
        and resource.pid is None
        and resource.pgid is None
        and resource.process_start_signature is None
    ):
        return True
    raise MigrationError("legacy Action external resource has no cleanup authority")


def _normalized_absolute_path(raw: str | None) -> Path | None:
    if raw is None:
        return None
    path = Path(os.path.normpath(raw))
    return path if path.is_absolute() else None


def _marks(values: tuple[str, ...]) -> str:
    return ",".join("?" for _ in values)


def _text(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError("legacy Action authority text is incomplete")
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)
