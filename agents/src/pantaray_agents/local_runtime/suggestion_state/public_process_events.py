from __future__ import annotations

import json
import sqlite3

from ..public_events import normalize_public_event_name


class PublicProcessEventConflictError(ValueError):
    pass


class PublicProcessEventActionOwnerError(ValueError):
    pass


class PublicProcessEventSequenceConflictError(ValueError):
    pass


def append_public_process_event(
    *,
    connection: sqlite3.Connection,
    event_id: str,
    suggestion_id: str | None,
    user_id: str,
    action_id: str | None,
    event_name: str,
    payload: dict[str, object],
    created_at: str | None = None,
    reserved_action_sequence: int | None = None,
) -> int:
    persisted_event_name = normalize_public_event_name(event_name=event_name)
    persisted_action_id = _resolve_persisted_action_id(
        connection=connection,
        action_id=action_id,
        user_id=user_id,
    )
    existing_sequence = _read_existing_event_sequence(
        connection=connection,
        event_id=event_id,
        suggestion_id=suggestion_id,
        user_id=user_id,
        action_id=persisted_action_id,
        event_name=persisted_event_name,
        payload=payload,
        created_at=created_at,
    )
    if existing_sequence is not None:
        return existing_sequence

    next_sequence = _next_public_process_event_sequence(
        connection=connection,
        suggestion_id=suggestion_id,
        action_id=persisted_action_id,
    )
    sequence = _resolve_reserved_action_sequence(
        connection=connection,
        suggestion_id=suggestion_id,
        action_id=persisted_action_id,
        next_sequence=next_sequence,
        reserved_sequence=reserved_action_sequence,
    )
    if created_at is None:
        connection.execute(
            """
            INSERT INTO agent_process_events(
                event_id,
                suggestion_id,
                user_id,
                action_id,
                sequence,
                event_name,
                payload,
                created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
            """,
            (
                event_id,
                suggestion_id,
                user_id,
                persisted_action_id,
                sequence,
                persisted_event_name,
                json.dumps(payload, ensure_ascii=False),
            ),
        )
        return sequence
    connection.execute(
        """
        INSERT INTO agent_process_events(
            event_id,
            suggestion_id,
            user_id,
            action_id,
            sequence,
            event_name,
            payload,
            created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            event_id,
            suggestion_id,
            user_id,
            persisted_action_id,
            sequence,
            persisted_event_name,
            json.dumps(payload, ensure_ascii=False),
            created_at,
        ),
    )
    return sequence


def read_public_process_event_sequence(
    *,
    connection: sqlite3.Connection,
    event_id: str,
    suggestion_id: str | None,
    action_id: str | None,
    event_name: str,
) -> int | None:
    persisted_event_name = normalize_public_event_name(event_name=event_name)
    persisted_action_id = _resolve_persisted_action_id(
        connection=connection,
        action_id=action_id,
        user_id=None,
    )
    return _read_existing_event_sequence(
        connection=connection,
        event_id=event_id,
        suggestion_id=suggestion_id,
        user_id=None,
        action_id=persisted_action_id,
        event_name=persisted_event_name,
        payload=None,
        created_at=None,
    )


def _read_existing_event_sequence(
    *,
    connection: sqlite3.Connection,
    event_id: str,
    suggestion_id: str | None,
    user_id: str | None,
    action_id: str | None,
    event_name: str,
    payload: dict[str, object] | None,
    created_at: str | None,
) -> int | None:
    row = connection.execute(
        """
        SELECT suggestion_id, user_id, action_id, event_name, payload, sequence,
               created_at
        FROM agent_process_events
        WHERE event_id = ?
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()
    if row is None:
        return None

    existing_suggestion_id = _normalize_optional_string(row["suggestion_id"])
    existing_user_id = str(row["user_id"])
    existing_action_id = _normalize_optional_string(row["action_id"])
    existing_event_name = str(row["event_name"])
    if (
        existing_suggestion_id != suggestion_id
        or (user_id is not None and existing_user_id != user_id)
        or existing_action_id != action_id
        or existing_event_name != event_name
        or (created_at is not None and str(row["created_at"]) != created_at)
        or (
            payload is not None
            and _canonical_json_payload(row["payload"])
            != _canonical_json_payload(payload)
        )
    ):
        raise PublicProcessEventConflictError(
            "public process event_id already belongs to a different event"
        )
    return int(row["sequence"])


def _resolve_reserved_action_sequence(
    *,
    connection: sqlite3.Connection,
    suggestion_id: str | None,
    action_id: str | None,
    next_sequence: int,
    reserved_sequence: int | None,
) -> int:
    if reserved_sequence is None:
        return next_sequence
    if (
        isinstance(reserved_sequence, bool)
        or reserved_sequence <= 0
        or suggestion_id is not None
        or action_id is None
        or reserved_sequence != next_sequence - 1
    ):
        raise PublicProcessEventSequenceConflictError(
            "reserved Action event sequence does not match durable acceptance order"
        )
    collision = connection.execute(
        "SELECT 1 FROM agent_process_events WHERE action_id = ? AND sequence = ?",
        (action_id, reserved_sequence),
    ).fetchone()
    if collision is not None:
        raise PublicProcessEventSequenceConflictError(
            "reserved Action event sequence already belongs to another event"
        )
    return reserved_sequence


def _next_public_process_event_sequence(
    *,
    connection: sqlite3.Connection,
    suggestion_id: str | None,
    action_id: str | None,
) -> int:
    if suggestion_id is None and action_id is None:
        raise ValueError("Action public events require an existing action_id")
    if action_id is None:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(sequence), 0)
            FROM agent_process_events
            WHERE suggestion_id = ?
            """,
            (suggestion_id,),
        ).fetchone()
    elif _has_action_accepted_sequence(connection):
        row = connection.execute(
            """
            SELECT COALESCE(MAX(candidate.sequence), 0)
            FROM (
                SELECT sequence
                FROM agent_process_events
                WHERE action_id = ?
                UNION ALL
                SELECT accepted_sequence AS sequence
                FROM agent_action_steps
                WHERE action_id = ? AND accepted_sequence IS NOT NULL
                UNION ALL
                SELECT sequence
                FROM agent_process_events
                WHERE suggestion_id = ?
            ) AS candidate
            """,
            (action_id, action_id, suggestion_id),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT COALESCE(MAX(candidate.sequence), 0)
            FROM (
                SELECT sequence
                FROM agent_process_events
                WHERE action_id = ?
                UNION ALL
                SELECT sequence
                FROM agent_process_events
                WHERE suggestion_id = ?
            ) AS candidate
            """,
            (action_id, suggestion_id),
        ).fetchone()
    return 1 if row is None else int(row[0]) + 1


def _has_action_accepted_sequence(connection: sqlite3.Connection) -> bool:
    return any(
        str(row[1]) == "accepted_sequence"
        for row in connection.execute("PRAGMA table_info(agent_action_steps)")
    )


def _resolve_persisted_action_id(
    *,
    connection: sqlite3.Connection,
    action_id: str | None,
    user_id: str | None,
) -> str | None:
    if action_id is None:
        return None
    row = connection.execute(
        "SELECT action_id FROM agent_actions "
        "WHERE action_id = ? AND (? IS NULL OR user_id = ?)",
        (action_id, user_id, user_id),
    ).fetchone()
    if row is None:
        raise PublicProcessEventActionOwnerError(
            "public process event action_id has no canonical Action owner"
        )
    return str(row[0])


def _normalize_optional_string(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    return normalized or None


def _canonical_json_payload(value: object) -> str:
    if isinstance(value, str):
        decoded = json.loads(value)
        if not isinstance(decoded, dict):
            raise PublicProcessEventConflictError(
                "stored public process event payload is not a JSON object"
            )
        return json.dumps(
            decoded, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    if isinstance(value, dict):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    raise PublicProcessEventConflictError(
        "public process event payload must be an object"
    )
