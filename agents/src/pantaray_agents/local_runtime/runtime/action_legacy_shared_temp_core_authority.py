from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import NamedTuple, cast

from ..storage.migrations import MigrationError
from ..tooling.action_session_temp_paths import resolve_action_storage_paths
from ..tooling.resources.resource_db_support import configure_connection

_KNOWN_LEGACY_CHECKPOINT_VERSIONS = frozenset({1, 2, 3, 4})


class LegacyManifestEvidence(NamedTuple):
    manifest_id: str
    user_id: str
    execution_session_id: str
    status: str
    scratch_root_path: str


class LegacySessionEvidence(NamedTuple):
    execution_session_id: str
    user_id: str
    action_id: str
    parent_execution_session_id: str | None
    status: str
    cwd_path: str
    action_temp_dir: str
    app_runtime_python: str
    network_policy: str
    read_access_scope: str


class LegacyCheckpointEvidence(NamedTuple):
    step_id: str
    user_id: str
    version: int
    raw_json: str


class LegacyActionSharedTempCoreAuthority(NamedTuple):
    user_id: str
    action_id: str
    fixed_root_path: Path
    manifest: LegacyManifestEvidence
    sessions: tuple[LegacySessionEvidence, ...]
    checkpoints: tuple[LegacyCheckpointEvidence, ...]


def load_legacy_action_shared_temp_core_authorities(
    *, db_path: Path, busy_timeout_ms: int
) -> tuple[LegacyActionSharedTempCoreAuthority, ...]:
    resolved_db_path = db_path.resolve()
    database_uri = f"{resolved_db_path.as_uri()}?mode=ro"
    with sqlite3.connect(database_uri, uri=True) as connection:
        configure_connection(connection, busy_timeout_ms)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
        return list_legacy_action_shared_temp_core_authorities_in_connection(
            connection=connection, resolved_db_path=resolved_db_path
        )


def list_legacy_action_shared_temp_core_authorities_in_connection(
    *, connection: sqlite3.Connection, resolved_db_path: Path
) -> tuple[LegacyActionSharedTempCoreAuthority, ...]:
    actions = connection.execute(
        """SELECT actions.user_id, actions.action_id FROM agent_actions AS actions
           WHERE EXISTS (SELECT 1 FROM execution_sessions AS sessions
                         WHERE sessions.action_id = actions.action_id)
              OR EXISTS (SELECT 1 FROM agent_action_steps AS steps
                         WHERE steps.action_id = actions.action_id
                           AND steps.runtime_state_checkpoint IS NOT NULL)
           ORDER BY actions.action_id"""
    ).fetchall()
    authorities: list[LegacyActionSharedTempCoreAuthority] = []
    for action in actions:
        authority = _load_candidate(
            connection=connection,
            resolved_db_path=resolved_db_path,
            user_id=_text(action["user_id"], "Action user_id"),
            action_id=_text(action["action_id"], "Action action_id"),
        )
        if authority is not None:
            authorities.append(authority)
    return tuple(authorities)


def _load_candidate(
    *,
    connection: sqlite3.Connection,
    resolved_db_path: Path,
    user_id: str,
    action_id: str,
) -> LegacyActionSharedTempCoreAuthority | None:
    paths = resolve_action_storage_paths(
        db_path=resolved_db_path, user_id=user_id, action_id=action_id
    )
    sessions = _query(
        connection,
        """WITH RECURSIVE related AS (
               SELECT * FROM execution_sessions WHERE action_id = ?
               UNION
               SELECT child.* FROM execution_sessions AS child
               JOIN related AS parent
                 ON child.parent_execution_session_id = parent.execution_session_id
           ) SELECT * FROM related ORDER BY execution_session_id""",
        action_id,
    )
    checkpoints = _query(
        connection,
        """SELECT step_id,user_id,runtime_state_checkpoint_version,
                  runtime_state_checkpoint FROM agent_action_steps
           WHERE action_id = ? AND runtime_state_checkpoint IS NOT NULL
           ORDER BY step_id""",
        action_id,
    )
    fixed_root = str(paths.session_temp_root)
    if not _has_fixed_root_hint(sessions, checkpoints, fixed_root=fixed_root):
        return None
    manifest = _load_manifest(connection, action_id=action_id)
    session_evidence = tuple(_session_evidence(row) for row in sessions)
    _validate_manifest_and_sessions(
        manifest,
        session_evidence,
        user_id=user_id,
        action_id=action_id,
        workspace=str(paths.workspace),
        fixed_root=fixed_root,
    )
    checkpoint_evidence = tuple(
        _checkpoint_evidence(
            row,
            user_id=user_id,
            action_id=action_id,
            manifest=manifest,
            sessions=session_evidence,
            fixed_root=fixed_root,
        )
        for row in checkpoints
    )
    return LegacyActionSharedTempCoreAuthority(
        user_id=user_id,
        action_id=action_id,
        fixed_root_path=paths.session_temp_root,
        manifest=manifest,
        sessions=session_evidence,
        checkpoints=checkpoint_evidence,
    )


def _load_manifest(
    connection: sqlite3.Connection, *, action_id: str
) -> LegacyManifestEvidence:
    rows = connection.execute(
        """SELECT manifest_id,user_id,execution_session_id,status,scratch_root_path
           FROM workspace_manifests WHERE action_id = ? ORDER BY manifest_id""",
        (action_id,),
    ).fetchall()
    if len(rows) != 1:
        raise MigrationError("legacy Action ready manifest evidence is incomplete")
    row = rows[0]
    return LegacyManifestEvidence(
        manifest_id=_text(row["manifest_id"], "manifest id"),
        user_id=_text(row["user_id"], "manifest user_id"),
        execution_session_id=_text(
            row["execution_session_id"], "manifest execution_session_id"
        ),
        status=_text(row["status"], "manifest status"),
        scratch_root_path=_text(row["scratch_root_path"], "manifest scratch path"),
    )


def _has_fixed_root_hint(
    sessions: tuple[sqlite3.Row, ...],
    checkpoints: tuple[sqlite3.Row, ...],
    *,
    fixed_root: str,
) -> bool:
    return any(row["action_temp_dir"] == fixed_root for row in sessions) or any(
        _decode_checkpoint(row["runtime_state_checkpoint"]).get("action_temp_dir")
        == fixed_root
        for row in checkpoints
    )


def _session_evidence(row: sqlite3.Row) -> LegacySessionEvidence:
    return LegacySessionEvidence(
        execution_session_id=_text(row["execution_session_id"], "session id"),
        user_id=_text(row["user_id"], "session user_id"),
        action_id=_text(row["action_id"], "session action_id"),
        parent_execution_session_id=_optional_text(
            row["parent_execution_session_id"], "parent session id"
        ),
        status=_text(row["status"], "session status"),
        cwd_path=_text(row["cwd_path"], "session cwd"),
        action_temp_dir=_text(row["action_temp_dir"], "session temp path"),
        app_runtime_python=_text(row["app_runtime_python"], "session Python"),
        network_policy=_text(row["network_policy"], "session network policy"),
        read_access_scope=_text(row["read_access_scope"], "session read scope"),
    )


def _validate_manifest_and_sessions(
    manifest: LegacyManifestEvidence,
    sessions: tuple[LegacySessionEvidence, ...],
    *,
    user_id: str,
    action_id: str,
    workspace: str,
    fixed_root: str,
) -> None:
    session_by_id = {row.execution_session_id: row for row in sessions}
    if (
        not sessions
        or manifest.user_id != user_id
        or manifest.status != "ready"
        or manifest.scratch_root_path != workspace
        or manifest.execution_session_id not in session_by_id
        or any(
            row.user_id != user_id
            or row.action_id != action_id
            or row.cwd_path != workspace
            or row.action_temp_dir != fixed_root
            for row in sessions
        )
    ):
        raise MigrationError("legacy Action manifest/session authority is inconsistent")
    parents = {
        row.execution_session_id: row.parent_execution_session_id for row in sessions
    }
    if any(parent is not None and parent not in parents for parent in parents.values()):
        raise MigrationError("legacy Action session tree crosses ownership")
    for session_id in parents:
        seen: set[str] = set()
        current: str | None = session_id
        while current is not None:
            if current in seen:
                raise MigrationError("legacy Action session tree contains a cycle")
            seen.add(current)
            current = parents[current]


def _checkpoint_evidence(
    row: sqlite3.Row,
    *,
    user_id: str,
    action_id: str,
    manifest: LegacyManifestEvidence,
    sessions: tuple[LegacySessionEvidence, ...],
    fixed_root: str,
) -> LegacyCheckpointEvidence:
    row_user_id = _text(row["user_id"], "checkpoint user_id")
    raw_json = _text(row["runtime_state_checkpoint"], "checkpoint JSON")
    version = row["runtime_state_checkpoint_version"]
    if (
        row_user_id != user_id
        or isinstance(version, bool)
        or not isinstance(version, int)
        or version not in _KNOWN_LEGACY_CHECKPOINT_VERSIONS
    ):
        raise MigrationError("legacy Action checkpoint row authority is inconsistent")
    payload = _decode_checkpoint(raw_json)
    if (
        _text(payload.get("action_id"), "checkpoint payload action_id") != action_id
        or _text(payload.get("user_id"), "checkpoint payload user_id") != user_id
    ):
        raise MigrationError(
            "legacy Action checkpoint payload ownership is inconsistent"
        )
    context_values = (
        payload.get("manifest_id"),
        payload.get("execution_session_id"),
        payload.get("execution_network_policy"),
        payload.get("action_temp_dir"),
        payload.get("app_runtime_python"),
        payload.get("read_access_scope"),
    )
    if any(value is not None for value in context_values):
        if not all(
            isinstance(value, str) and bool(value.strip()) for value in context_values
        ):
            raise MigrationError("legacy Action checkpoint context is incomplete")
        manifest_id, session_id, network_policy, action_temp_dir, python, read_scope = (
            cast(tuple[str, str, str, str, str, str], context_values)
        )
        session_by_id = {session.execution_session_id: session for session in sessions}
        session = session_by_id.get(session_id)
        if (
            session is None
            or manifest_id != manifest.manifest_id
            or action_temp_dir != fixed_root
            or network_policy != session.network_policy
            or python != session.app_runtime_python
            or read_scope != session.read_access_scope
        ):
            raise MigrationError("legacy Action checkpoint context is inconsistent")
    return LegacyCheckpointEvidence(
        step_id=_text(row["step_id"], "checkpoint step_id"),
        user_id=row_user_id,
        version=version,
        raw_json=raw_json,
    )


def _decode_checkpoint(raw: object) -> dict[str, object]:
    try:
        decoded = json.loads(_text(raw, "checkpoint JSON"))
    except ValueError as exc:
        raise MigrationError("legacy Action checkpoint is invalid JSON") from exc
    if not isinstance(decoded, dict):
        raise MigrationError("legacy Action checkpoint must be a JSON object")
    return cast(dict[str, object], decoded)


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise MigrationError(f"{field} is incomplete")
    return value


def _optional_text(value: object, field: str) -> str | None:
    return None if value is None else _text(value, field)


def _query(
    connection: sqlite3.Connection, query: str, action_id: str
) -> tuple[sqlite3.Row, ...]:
    return tuple(connection.execute(query, (action_id,)).fetchall())
