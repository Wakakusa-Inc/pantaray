import json
import sqlite3
from dataclasses import dataclass, replace
from typing import Never

from .specs import MigrationError

_ACTIVE_JOB_STATUSES = ("queued", "running", "paused", "retryable_error", "blocked")
_ACTIVE_PROCESS_STATUSES = ("enqueued", "running", "paused")


@dataclass(frozen=True)
class InflightActionLineage:
    suggestion_id: str
    user_id: str
    action_id: str
    process_id: str
    command_id: str
    accepted_at: str
    action_status: str
    job_id: str | None = None


def cutover_internal_event_id(process_id: str) -> str:
    return f"v82-cutover-internal:{process_id}"


def cutover_public_event_id(suggestion_id: str) -> str:
    return f"v82-cutover-public:{suggestion_id}"


def load_validated_inflight_action_lineages(
    connection: sqlite3.Connection,
) -> tuple[InflightActionLineage, ...]:
    connection.row_factory = sqlite3.Row
    lineages = _load_inflight_lineages(connection)
    if not lineages:
        return ()
    lineages = _bind_active_jobs(connection, lineages)
    _require_runtime_ownership(connection, lineages)
    return lineages


def _load_inflight_lineages(
    connection: sqlite3.Connection,
) -> tuple[InflightActionLineage, ...]:
    rows = connection.execute(
        """
        SELECT
            suggestion_id,
            user_id,
            action_status,
            action_request_payload,
            action_process_id,
            action_execution_id,
            action_command_id,
            accepted_at
        FROM agent_suggestions
        WHERE user_reaction = 'accepted'
          AND (
              action_status IS NULL
              OR action_status NOT IN ('success', 'error', 'canceled')
              OR action_request_payload IS NOT NULL
          )
        ORDER BY suggestion_id
        """
    ).fetchall()
    lineages: list[InflightActionLineage] = []
    for row in rows:
        suggestion_id = _required_identifier(
            row["suggestion_id"], category="accepted_suggestion", identifier="missing"
        )
        status = str(row["action_status"] or "")
        if status not in {"idle", "processing"}:
            _reject(
                "accepted_suggestion",
                suggestion_id,
                f"invalid_status:{status or 'missing'}",
            )
        has_request_payload = row["action_request_payload"] is not None
        if has_request_payload != (status == "idle"):
            _reject(
                "accepted_suggestion",
                suggestion_id,
                "request_payload_state_mismatch",
            )
        lineage = InflightActionLineage(
            suggestion_id=suggestion_id,
            user_id=_required_identifier(
                row["user_id"], category="accepted_suggestion", identifier=suggestion_id
            ),
            action_id=_required_identifier(
                row["action_execution_id"],
                category="accepted_suggestion",
                identifier=suggestion_id,
            ),
            process_id=_required_identifier(
                row["action_process_id"],
                category="accepted_suggestion",
                identifier=suggestion_id,
            ),
            command_id=_required_identifier(
                row["action_command_id"],
                category="accepted_suggestion",
                identifier=suggestion_id,
            ),
            accepted_at=_required_text(
                row["accepted_at"],
                category="accepted_suggestion",
                identifier=suggestion_id,
                field_name="accepted_at",
            ),
            action_status=status,
        )
        _require_action_state(connection, lineage)
        lineages.append(lineage)
    _require_unique_lineage_ids(lineages)
    _require_all_processing_actions_are_bound(connection, lineages)
    return tuple(lineages)


def _require_action_state(
    connection: sqlite3.Connection, lineage: InflightActionLineage
) -> None:
    rows = connection.execute(
        """
        SELECT action_id, user_id, suggestion_id, status
        FROM agent_actions
        WHERE action_id = ? OR suggestion_id = ?
        ORDER BY action_id
        """,
        (lineage.action_id, lineage.suggestion_id),
    ).fetchall()
    if lineage.action_status == "idle":
        if rows:
            _reject(
                "action_suggestion_link",
                lineage.action_id,
                "unclaimed_suggestion_has_action",
            )
        return
    if len(rows) != 1:
        _reject(
            "action_suggestion_link",
            lineage.action_id,
            f"processing_action_count:{len(rows)}",
        )
    row = rows[0]
    actual = (str(row["user_id"]), str(row["suggestion_id"]), str(row["status"]))
    expected = (lineage.user_id, lineage.suggestion_id, "processing")
    if str(row["action_id"]) != lineage.action_id or actual != expected:
        _reject("action_suggestion_link", lineage.action_id, "owner_mismatch")


def _require_unique_lineage_ids(lineages: list[InflightActionLineage]) -> None:
    for field_name in ("action_id", "process_id"):
        seen: set[str] = set()
        for lineage in lineages:
            value = getattr(lineage, field_name)
            if value in seen:
                _reject("action_lineage", value, f"duplicate_{field_name}")
            seen.add(value)


def _require_all_processing_actions_are_bound(
    connection: sqlite3.Connection, lineages: list[InflightActionLineage]
) -> None:
    bound_action_ids = {
        lineage.action_id
        for lineage in lineages
        if lineage.action_status == "processing"
    }
    rows = connection.execute(
        """
        SELECT action_id
        FROM agent_actions
        WHERE status NOT IN ('success', 'error', 'canceled')
        ORDER BY action_id
        """
    ).fetchall()
    for row in rows:
        action_id = str(row["action_id"])
        if action_id not in bound_action_ids:
            _reject("action", action_id, "orphan_inflight_action")


def _bind_active_jobs(
    connection: sqlite3.Connection,
    lineages: tuple[InflightActionLineage, ...],
) -> tuple[InflightActionLineage, ...]:
    by_action_id = {lineage.action_id: lineage for lineage in lineages}
    bound_jobs: dict[str, sqlite3.Row] = {}
    rows = connection.execute(
        """
        SELECT jobs.*, payloads.payload_json
        FROM jobs
        LEFT JOIN job_payloads AS payloads ON payloads.job_id = jobs.job_id
        WHERE jobs.job_type = 'execute_action'
          AND jobs.status IN (?, ?, ?, ?, ?)
        ORDER BY jobs.job_id
        """,
        _ACTIVE_JOB_STATUSES,
    ).fetchall()
    for row in rows:
        job_id = str(row["job_id"])
        payload = _decode_payload(row["payload_json"], job_id=job_id)
        action_id = _payload_identifier(payload, "action_id", job_id=job_id)
        lineage = by_action_id.get(action_id)
        if lineage is None:
            _reject("action_job", job_id, "orphan_inflight_job")
        if action_id in bound_jobs:
            _reject("action_job", job_id, f"duplicate_action:{action_id}")
        _require_job_identity(row, payload, lineage)
        bound_jobs[action_id] = row
    missing_action_ids = sorted(set(by_action_id) - set(bound_jobs))
    if missing_action_ids:
        _reject("action_job", missing_action_ids[0], "missing_inflight_job")
    return tuple(
        replace(lineage, job_id=str(bound_jobs[lineage.action_id]["job_id"]))
        for lineage in lineages
    )


def _require_job_identity(
    row: sqlite3.Row,
    payload: dict[str, object],
    lineage: InflightActionLineage,
) -> None:
    job_id = str(row["job_id"])
    expected_payload = {
        "job_id": job_id,
        "process_id": lineage.process_id,
        "action_id": lineage.action_id,
        "suggestion_id": lineage.suggestion_id,
        "user_id": lineage.user_id,
        "command_id": lineage.command_id,
        "accepted_at": lineage.accepted_at,
    }
    for field_name, expected in expected_payload.items():
        if _payload_identifier(payload, field_name, job_id=job_id) != expected:
            _reject("action_job", job_id, f"payload_{field_name}_mismatch")
    dispatch_kind = _payload_identifier(payload, "dispatch_kind", job_id=job_id)
    if dispatch_kind not in {"start", "approval_resume"}:
        _reject("action_job", job_id, f"invalid_dispatch_kind:{dispatch_kind}")
    if str(row["user_id"]) != lineage.user_id:
        _reject("action_job", job_id, "owner_mismatch")
    if str(row["process_id"] or "") != lineage.process_id:
        _reject("action_job", job_id, "process_mismatch")
    if str(row["logical_key"] or "") != lineage.action_id:
        _reject("action_job", job_id, "logical_key_mismatch")


def _require_runtime_ownership(
    connection: sqlite3.Connection,
    lineages: tuple[InflightActionLineage, ...],
) -> None:
    by_action_id = {lineage.action_id: lineage for lineage in lineages}
    by_process_id = {lineage.process_id: lineage for lineage in lineages}
    _require_active_processes(connection, by_process_id)
    _require_running_attempts(connection, lineages)
    _require_action_owned_rows(connection, by_action_id)
    _require_event_slots(connection, lineages)


def _require_active_processes(
    connection: sqlite3.Connection,
    by_process_id: dict[str, InflightActionLineage],
) -> None:
    rows = connection.execute(
        """
        SELECT process_id, user_id, kind, suggestion_id, action_id
        FROM processes
        WHERE kind = 'action'
          AND status IN (?, ?, ?)
        ORDER BY process_id
        """,
        _ACTIVE_PROCESS_STATUSES,
    ).fetchall()
    seen: set[str] = set()
    for row in rows:
        process_id = str(row["process_id"])
        lineage = by_process_id.get(process_id)
        if lineage is None:
            _reject("action_process", process_id, "orphan_inflight_process")
        actual = (
            str(row["user_id"]),
            str(row["suggestion_id"] or ""),
            str(row["action_id"] or ""),
        )
        expected = (lineage.user_id, lineage.suggestion_id, lineage.action_id)
        if str(row["kind"]) != "action" or actual != expected:
            _reject("action_process", process_id, "owner_mismatch")
        seen.add(process_id)
    missing = sorted(set(by_process_id) - seen)
    if missing:
        _reject("action_process", missing[0], "missing_inflight_process")


def _require_running_attempts(
    connection: sqlite3.Connection, lineages: tuple[InflightActionLineage, ...]
) -> None:
    job_ids = {lineage.job_id for lineage in lineages}
    seen_jobs: set[str] = set()
    rows = connection.execute(
        """
        SELECT attempt_id, job_id
        FROM job_attempts
        WHERE status = 'running'
        ORDER BY attempt_id
        """
    ).fetchall()
    for row in rows:
        attempt_id = str(row["attempt_id"])
        job_id = str(row["job_id"])
        if job_id not in job_ids:
            _reject("action_attempt", attempt_id, "orphan_running_attempt")
        if job_id in seen_jobs:
            _reject("action_attempt", attempt_id, f"duplicate_job:{job_id}")
        seen_jobs.add(job_id)


def _require_action_owned_rows(
    connection: sqlite3.Connection,
    by_action_id: dict[str, InflightActionLineage],
) -> None:
    queries = (
        ("approval", "approval_sessions", "approval_session_id", "status = 'pending'"),
        (
            "tool_invocation",
            "tool_invocations",
            "invocation_id",
            "status IN ('queued', 'running')",
        ),
        (
            "execution_session",
            "execution_sessions",
            "execution_session_id",
            "status = 'running' AND action_id IS NOT NULL",
        ),
    )
    for category, table_name, id_column, predicate in queries:
        rows = connection.execute(
            f"""
            SELECT {id_column}, user_id, action_id
            FROM {table_name}
            WHERE {predicate}
            ORDER BY {id_column}
            """
        ).fetchall()
        for row in rows:
            identifier = str(row[id_column])
            action_id = str(row["action_id"])
            lineage = by_action_id.get(action_id)
            if lineage is None or lineage.action_status != "processing":
                _reject(category, identifier, "orphan_inflight_row")
            if str(row["user_id"]) != lineage.user_id:
                _reject(category, identifier, "owner_mismatch")


def _require_event_slots(
    connection: sqlite3.Connection,
    lineages: tuple[InflightActionLineage, ...],
) -> None:
    for lineage in lineages:
        row = connection.execute(
            """
            SELECT event_id FROM process_events WHERE event_id = ?
            UNION ALL
            SELECT event_id FROM agent_process_events WHERE event_id = ?
            UNION ALL
            SELECT events.event_id
            FROM processes
            JOIN process_events AS events
              ON events.process_id = processes.process_id
             AND events.event_seq = processes.next_event_seq
            WHERE processes.process_id = ?
            LIMIT 1
            """,
            (
                cutover_internal_event_id(lineage.process_id),
                cutover_public_event_id(lineage.suggestion_id),
                lineage.process_id,
            ),
        ).fetchone()
        if row is not None:
            _reject("action_event", str(row["event_id"]), "identity_conflict")


def _decode_payload(raw: object, *, job_id: str) -> dict[str, object]:
    payload = json.loads(raw) if isinstance(raw, str) else None
    if not isinstance(payload, dict):
        _reject("action_job", job_id, "missing_or_nonobject_payload")
    return payload


def _payload_identifier(
    payload: dict[str, object], field_name: str, *, job_id: str
) -> str:
    return _required_identifier(
        payload.get(field_name), category="action_job", identifier=job_id
    )


def _required_identifier(value: object, *, category: str, identifier: str) -> str:
    normalized = _required_text(
        value,
        category=category,
        identifier=identifier,
        field_name="identity",
    )
    if normalized != value:
        _reject(category, identifier, "noncanonical_identity")
    return normalized


def _required_text(
    value: object,
    *,
    category: str,
    identifier: str,
    field_name: str,
) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(category, identifier, f"missing_{field_name}")
    return value.strip()


def _reject(category: str, identifier: str, status: str) -> Never:
    raise MigrationError(
        f"v82 preflight blocked: category={category} id={identifier} status={status}"
    )


__all__ = [
    "InflightActionLineage",
    "cutover_internal_event_id",
    "cutover_public_event_id",
    "load_validated_inflight_action_lineages",
]
