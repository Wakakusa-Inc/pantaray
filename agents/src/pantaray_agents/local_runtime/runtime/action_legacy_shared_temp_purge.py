from __future__ import annotations

import sqlite3
import uuid
from contextlib import closing
from pathlib import Path

from ..descriptor_access import DescriptorPathError
from ..storage.migrations import MigrationError
from ..storage.transactions import immediate_transaction
from ..suggestion_state.public_projection import rebuild_history_projection
from ..tooling.action_session_temp_paths import SCRATCH_SESSION_TEMP_DIRNAME
from ..tooling.resources.action_session_temp_cleanup import (
    DescriptorSafeRemovalUnavailableError,
    remove_descriptor_confined_directory_child,
)
from ..tooling.resources.resource_db_support import configure_connection
from .action_legacy_shared_temp_blocker_cleanup import (
    reconcile_legacy_action_shared_temp_blockers,
)
from .action_legacy_shared_temp_resource_authority import (
    LegacyActionSharedTempPrecleanupAuthority,
    list_legacy_action_shared_temp_precleanup_authorities_in_connection,
)
from .action_legacy_shared_temp_suggestion_projection_authority import (
    LegacyActionSharedTempSuggestionProjectionAuthority,
    list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection,
)
from .job_status import JOB_STATUS_QUEUED, JOB_STATUS_RUNNING
from .job_types import LOCAL_AGENT_EXPERIENCE_JOB_TYPE

_UNFINISHED_AGENT_EXPERIENCE_JOB_STATUSES = frozenset(
    {JOB_STATUS_QUEUED, JOB_STATUS_RUNNING}
)


def purge_legacy_action_shared_temp_for_startup(
    *, db_path: Path, busy_timeout_ms: int
) -> int:
    """Delete verified legacy shared roots and their incompatible Actions."""

    resolved_db_path = db_path.resolve()
    precleanup = _load_precleanup_authorities(
        resolved_db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
    )
    reconcile_legacy_action_shared_temp_blockers(
        resolved_db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
        authorities=precleanup,
    )
    authorities = _purge_candidates(
        _load_strict_authorities(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    )
    for authority in authorities:
        try:
            remove_descriptor_confined_directory_child(
                parent_path=authority.runtime_authority.resource_authority.core.fixed_root_path.parent,
                child_name=SCRATCH_SESSION_TEMP_DIRNAME,
            )
        except (
            OSError,
            DescriptorPathError,
            DescriptorSafeRemovalUnavailableError,
        ) as exc:
            raise MigrationError(
                "legacy Action shared temp root deletion failed"
            ) from exc
    _purge_authorities(
        resolved_db_path=resolved_db_path,
        busy_timeout_ms=busy_timeout_ms,
        authorities=authorities,
    )
    return len(authorities)


def _load_precleanup_authorities(
    *, resolved_db_path: Path, busy_timeout_ms: int
) -> tuple[LegacyActionSharedTempPrecleanupAuthority, ...]:
    with closing(
        _open_read_snapshot(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    ) as connection:
        return list_legacy_action_shared_temp_precleanup_authorities_in_connection(
            connection=connection,
            resolved_db_path=resolved_db_path,
        )


def _load_strict_authorities(
    *, resolved_db_path: Path, busy_timeout_ms: int
) -> tuple[LegacyActionSharedTempSuggestionProjectionAuthority, ...]:
    with closing(
        _open_read_snapshot(
            resolved_db_path=resolved_db_path,
            busy_timeout_ms=busy_timeout_ms,
        )
    ) as connection:
        return list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection(
            connection=connection,
            resolved_db_path=resolved_db_path,
        )


def _open_read_snapshot(
    *, resolved_db_path: Path, busy_timeout_ms: int
) -> sqlite3.Connection:
    database_uri = f"{resolved_db_path.as_uri()}?mode=ro"
    connection = sqlite3.connect(database_uri, uri=True)
    try:
        configure_connection(connection, busy_timeout_ms)
        connection.execute("PRAGMA query_only = ON")
        connection.execute("BEGIN")
    except BaseException:
        connection.close()
        raise
    return connection


def _purge_authorities(
    *,
    resolved_db_path: Path,
    busy_timeout_ms: int,
    authorities: tuple[LegacyActionSharedTempSuggestionProjectionAuthority, ...],
) -> None:
    if not authorities:
        return
    with sqlite3.connect(resolved_db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        with immediate_transaction(connection):
            current = _purge_candidates(
                list_legacy_action_shared_temp_suggestion_projection_authorities_in_connection(
                    connection=connection,
                    resolved_db_path=resolved_db_path,
                )
            )
            if current != authorities:
                raise MigrationError("legacy Action purge authority changed")
            for authority in authorities:
                _purge_action(connection=connection, authority=authority)
            connection.execute(
                """INSERT INTO runtime_recovery_runs(
                       recovery_run_id,status,note)
                   VALUES (?, 'completed', ?)""",
                (
                    str(uuid.uuid4()),
                    f"legacy_action_shared_temp_purge; purged_actions={len(authorities)}",
                ),
            )


def _purge_candidates(
    authorities: tuple[LegacyActionSharedTempSuggestionProjectionAuthority, ...],
) -> tuple[LegacyActionSharedTempSuggestionProjectionAuthority, ...]:
    return tuple(
        authority
        for authority in authorities
        if not any(
            job.job.job_type == LOCAL_AGENT_EXPERIENCE_JOB_TYPE
            and job.job.status in _UNFINISHED_AGENT_EXPERIENCE_JOB_STATUSES
            for process in authority.runtime_authority.processes
            for job in process.jobs
        )
    )


def _purge_action(
    *,
    connection: sqlite3.Connection,
    authority: LegacyActionSharedTempSuggestionProjectionAuthority,
) -> None:
    runtime = authority.runtime_authority
    action = runtime.action
    projection = authority.suggestion_projection
    if projection is not None:
        cursor = connection.execute(
            """UPDATE agent_suggestions
               SET action_status=NULL, action_failure_code=NULL,
                   action_failure_stage=NULL, action_failure_message_public=NULL,
                   action_request_payload=NULL, action_process_id=NULL,
                   action_command_id=NULL, action_started_at=NULL
               WHERE suggestion_id=? AND user_id=?""",
            (projection.suggestion.suggestion_id, projection.suggestion.user_id),
        )
        _require_row_count(cursor, expected=1, owner="Suggestion Action projection")

    _delete_exact_rows(
        connection=connection,
        statement="DELETE FROM tool_runtime_resource_events WHERE event_id=?",
        identities=tuple(row.event_id for row in runtime.resource_events),
        owner="resource events",
    )
    jobs = tuple(
        job.job.job_id for process in runtime.processes for job in process.jobs
    )
    _delete_exact_rows(
        connection=connection,
        statement="DELETE FROM jobs WHERE job_id=?",
        identities=jobs,
        owner="jobs",
    )
    if authority.action_memory is not None:
        memory = authority.action_memory
        cursor = connection.execute(
            """UPDATE memory_nodes AS nodes
               SET lifecycle='tombstoned',updated_at=strftime('%Y-%m-%dT%H:%M:%fZ','now')
               WHERE nodes.user_id=? AND nodes.node_id=?
                 AND nodes.source_type='action' AND nodes.source_record_id=?
                 AND nodes.lifecycle=? AND nodes.integrity=?
                 AND nodes.current_revision_id=? AND nodes.updated_at=?
                 AND EXISTS (
                   SELECT 1 FROM memory_revisions AS revisions
                   WHERE revisions.user_id=nodes.user_id AND revisions.node_id=nodes.node_id
                     AND revisions.revision_id=nodes.current_revision_id
                     AND revisions.body_kind=?)""",
            (memory.user_id, memory.node_id, action.action_id, *memory[2:]),
        )
        _require_row_count(cursor, expected=1, owner="Action memory")
    cursor = connection.execute(
        "DELETE FROM agent_actions WHERE action_id=? AND user_id=?",
        (action.action_id, action.user_id),
    )
    _require_row_count(cursor, expected=1, owner="Action")
    _delete_exact_rows(
        connection=connection,
        statement="DELETE FROM processes WHERE process_id=?",
        identities=tuple(row.process.process_id for row in runtime.processes),
        owner="processes",
    )
    if projection is not None:
        rebuild_history_projection(
            connection=connection,
            user_id=projection.suggestion.user_id,
            suggestion_id=projection.suggestion.suggestion_id,
        )


def _delete_exact_rows(
    *,
    connection: sqlite3.Connection,
    statement: str,
    identities: tuple[str, ...],
    owner: str,
) -> None:
    cursor = connection.executemany(statement, ((identity,) for identity in identities))
    _require_row_count(cursor, expected=len(identities), owner=owner)


def _require_row_count(cursor: sqlite3.Cursor, *, expected: int, owner: str) -> None:
    if cursor.rowcount != expected:
        raise MigrationError(
            f"legacy Action purge changed an invalid {owner} row count"
        )


__all__ = ["purge_legacy_action_shared_temp_for_startup"]
