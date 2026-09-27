from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.tasks.types import ActionSubagentJobPayload

from ..storage.migrations import MigrationError
from ..storage.migrations.connection import configure_connection
from .job_envelope import LocalJobEnvelopeIntegrityError
from .job_payload_models import serialize_action_subagent_job_payload
from .job_types import LOCAL_ACTION_JOB_TYPE, LOCAL_ACTION_SUBAGENT_JOB_TYPE


class ActionSubagentBrokerAuthorityError(LocalJobEnvelopeIntegrityError):
    pass


@dataclass(frozen=True, slots=True)
class ActionSubagentBrokerAuthority:
    manifest_id: str
    execution_session_id: str


def load_action_subagent_broker_authority(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    payload: ActionSubagentJobPayload,
) -> ActionSubagentBrokerAuthority:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")
    params = {
        **payload,
        "action_job_type": LOCAL_ACTION_JOB_TYPE,
        "child_job_type": LOCAL_ACTION_SUBAGENT_JOB_TYPE,
        "claim_count": len(payload["resource_claim_ids"]),
        "claim_ids_json": json.dumps(payload["resource_claim_ids"]),
        "payload_json": serialize_action_subagent_job_payload(payload),
    }
    with sqlite3.connect(db_path) as connection:
        configure_connection(connection, busy_timeout_ms)
        row = connection.execute(
            """
            SELECT manifest.manifest_id, session.execution_session_id
            FROM jobs AS child_job
            JOIN processes AS child
              ON child.process_id=child_job.process_id
             AND child.user_id=child_job.user_id
            JOIN job_payloads AS child_payload ON child_payload.job_id=child_job.job_id
            JOIN job_attempts AS child_attempt
              ON child_attempt.job_id=child_job.job_id
             AND child_attempt.attempt_number=child_job.attempt
            JOIN processes AS parent
              ON parent.process_id=child.parent_process_id
             AND parent.user_id=child.user_id
             AND parent.action_id=child.action_id
            JOIN jobs AS parent_job
              ON parent_job.job_id=parent.current_job_id
             AND parent_job.process_id=parent.process_id
             AND parent_job.user_id=parent.user_id
            JOIN agent_actions AS action
              ON action.action_id=child.action_id AND action.user_id=child.user_id
            JOIN workspace_manifests AS manifest
              ON manifest.action_id=action.action_id AND manifest.user_id=action.user_id
            JOIN execution_sessions AS session
              ON session.execution_session_id=manifest.execution_session_id
             AND session.action_id=action.action_id AND session.user_id=action.user_id
            WHERE child_job.job_id=:job_id AND child_job.user_id=:user_id
              AND child_job.job_type=:child_job_type
              AND child_job.status='running' AND child_job.attempt >= 1
              AND child_job.completed_at IS NULL
              AND child_job.logical_key=:job_id
              AND child.process_id=:process_id AND child.kind='action_subagent'
              AND child.status='running' AND child.action_id=:action_id
              AND child.parent_process_id=:parent_process_id
              AND child.current_job_id=child_job.job_id
              AND child.terminal_event_id IS NULL AND child.completed_at IS NULL
              AND child_attempt.status='running' AND child_attempt.completed_at IS NULL
              AND child_payload.payload_json=:payload_json
              AND parent.kind='action' AND parent.status='running'
              AND parent_job.job_type=:action_job_type
              AND parent_job.status='running' AND parent_job.completed_at IS NULL
              AND parent_job.logical_key=:action_id
              AND action.status='processing'
              AND manifest.status='ready'
              AND manifest.scratch_root_path=session.cwd_path
              AND session.parent_execution_session_id IS NULL
              AND session.status='running'
              AND (SELECT COUNT(*) FROM action_subagent_resource_claims AS claim
                   WHERE claim.user_id=:user_id AND claim.action_id=:action_id
                     AND claim.parent_process_id=:parent_process_id
                     AND claim.child_process_id=:process_id)=:claim_count
              AND (SELECT COUNT(*) FROM action_subagent_resource_claims AS claim
                   WHERE claim.user_id=:user_id AND claim.action_id=:action_id
                     AND claim.parent_process_id=:parent_process_id
                     AND claim.child_process_id=:process_id
                     AND claim.released_at IS NULL
                     AND claim.claim_id IN
                         (SELECT value FROM json_each(:claim_ids_json)))=:claim_count
            """,
            params,
        ).fetchone()
    if row is None:
        raise ActionSubagentBrokerAuthorityError(
            "Action subagent broker authority is not active"
        )
    return ActionSubagentBrokerAuthority(
        manifest_id=str(row[0]), execution_session_id=str(row[1])
    )
