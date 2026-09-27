from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.local_runtime.storage.migrations import MigrationError

from .job_types import PROCESS_KIND_BY_JOB_TYPE


class LocalJobEnvelopeIntegrityError(MigrationError):
    """Persisted job, process, or payload ownership is inconsistent."""


@dataclass(frozen=True, slots=True)
class LocalJobEnvelope:
    job_id: str
    job_type: str
    job_user_id: str
    process_id: str | None
    process_user_id: str | None
    process_kind: str | None
    process_status: str | None
    job_status: str
    logical_key: str | None
    payload_json: str | None
    attempt: int


def load_local_job_envelope(
    *,
    connection: sqlite3.Connection,
    job_id: str,
) -> LocalJobEnvelope | None:
    row = connection.execute(
        """
        SELECT j.job_id, j.job_type, j.user_id, j.process_id,
               p.user_id, p.kind, p.status, j.status, j.logical_key,
               jp.payload_json, j.attempt
        FROM jobs AS j
        LEFT JOIN processes AS p ON p.process_id = j.process_id
        LEFT JOIN job_payloads AS jp ON jp.job_id = j.job_id
        WHERE j.job_id = ?
        LIMIT 1
        """,
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    return LocalJobEnvelope(
        job_id=str(row[0]),
        job_type=str(row[1]),
        job_user_id=str(row[2]),
        process_id=str(row[3]) if row[3] is not None else None,
        process_user_id=str(row[4]) if row[4] is not None else None,
        process_kind=str(row[5]) if row[5] is not None else None,
        process_status=str(row[6]) if row[6] is not None else None,
        job_status=str(row[7]),
        logical_key=str(row[8]) if row[8] is not None else None,
        payload_json=str(row[9]) if row[9] is not None else None,
        attempt=int(row[10]),
    )


def require_valid_local_job_envelope(
    envelope: LocalJobEnvelope,
    *,
    expected_job_type: str | None = None,
    expected_user_id: str | None = None,
    expected_process_status: str | None = None,
) -> None:
    expected_process_kind = PROCESS_KIND_BY_JOB_TYPE.get(envelope.job_type)
    if expected_process_kind is None:
        raise LocalJobEnvelopeIntegrityError(
            f"local job has unsupported job_type: {envelope.job_type}"
        )
    if expected_job_type is not None and envelope.job_type != expected_job_type:
        raise LocalJobEnvelopeIntegrityError("local job type does not match its caller")
    if expected_user_id is not None and envelope.job_user_id != expected_user_id:
        raise LocalJobEnvelopeIntegrityError(
            "local job owner does not match its caller"
        )
    if envelope.process_id is None or envelope.process_user_id is None:
        raise LocalJobEnvelopeIntegrityError("local job has no process")
    if envelope.process_user_id != envelope.job_user_id:
        raise LocalJobEnvelopeIntegrityError(
            "local job and process owners do not match"
        )
    if envelope.process_kind != expected_process_kind:
        raise LocalJobEnvelopeIntegrityError(
            "local job type and process kind do not match"
        )
    if envelope.payload_json is None:
        raise LocalJobEnvelopeIntegrityError("local job has no payload")
    if (
        expected_process_status is not None
        and envelope.process_status != expected_process_status
    ):
        raise LocalJobEnvelopeIntegrityError(
            "local job and process statuses do not match"
        )


__all__ = [
    "LocalJobEnvelope",
    "LocalJobEnvelopeIntegrityError",
    "load_local_job_envelope",
    "require_valid_local_job_envelope",
]
