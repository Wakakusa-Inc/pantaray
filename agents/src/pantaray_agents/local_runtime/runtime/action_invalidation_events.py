from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.suggestion_state.public_process_events import (
    append_public_process_event,
)
from pantaray_agents.schema.action_conversation import (
    ActionMessageAcceptedEventData,
    ActionMessageAdoptedEventData,
)

ACTION_MESSAGE_ACCEPTED_EVENT = "action_message_accepted"
ACTION_MESSAGE_ADOPTED_EVENT = "action_message_adopted"

type ActionInvalidationEventData = (
    ActionMessageAcceptedEventData | ActionMessageAdoptedEventData
)


class ActionInvalidationTransactionError(RuntimeError):
    pass


class ActionInvalidationIdentityError(ValueError):
    pass


def _validate_action_step_identity(
    *,
    connection: sqlite3.Connection,
    user_id: str,
    data: ActionInvalidationEventData,
) -> int | None:
    row = connection.execute(
        """
        SELECT action_id, user_id, user_message_id, step_type, accepted_sequence,
               adopted_process_id
        FROM agent_action_steps
        WHERE step_id = ?
        """,
        (data.step_id,),
    ).fetchone()
    if row is None or (
        str(row["action_id"]) != data.action_id
        or str(row["user_id"]) != user_id
        or str(row["user_message_id"]) != data.message_id
        or str(row["step_type"]) != "user_request"
    ):
        raise ActionInvalidationIdentityError(
            "Action invalidation does not match its canonical USER step"
        )
    if (
        isinstance(data, ActionMessageAdoptedEventData)
        and row["adopted_process_id"] != data.process_id
    ):
        raise ActionInvalidationIdentityError(
            "Action adoption invalidation does not match its canonical process"
        )
    if isinstance(data, ActionMessageAcceptedEventData):
        accepted_sequence = row["accepted_sequence"]
        if (
            isinstance(accepted_sequence, bool)
            or not isinstance(accepted_sequence, int)
            or accepted_sequence <= 0
        ):
            raise ActionInvalidationIdentityError(
                "Action acceptance invalidation requires durable acceptance order"
            )
        return accepted_sequence
    return None


def append_action_invalidation_event(
    *,
    connection: sqlite3.Connection,
    event_id: str,
    user_id: str,
    data: ActionInvalidationEventData,
    created_at: str,
) -> int:
    """Append one identity-only Action invalidation in the Action namespace."""

    if not connection.in_transaction:
        raise ActionInvalidationTransactionError(
            "Action invalidation append requires a caller-owned transaction"
        )
    if isinstance(data, ActionMessageAcceptedEventData):
        event_name = ACTION_MESSAGE_ACCEPTED_EVENT
        payload = {
            "action_id": data.action_id,
            "message_id": data.message_id,
            "step_id": data.step_id,
        }
    elif isinstance(data, ActionMessageAdoptedEventData):
        event_name = ACTION_MESSAGE_ADOPTED_EVENT
        payload = {
            "action_id": data.action_id,
            "message_id": data.message_id,
            "step_id": data.step_id,
            "process_id": data.process_id,
        }
    else:
        raise TypeError("unsupported Action invalidation event data")
    reserved_action_sequence = _validate_action_step_identity(
        connection=connection,
        user_id=user_id,
        data=data,
    )
    return append_public_process_event(
        connection=connection,
        event_id=event_id,
        suggestion_id=None,
        user_id=user_id,
        action_id=data.action_id,
        event_name=event_name,
        payload={"data": payload},
        created_at=created_at,
        reserved_action_sequence=reserved_action_sequence,
    )


__all__ = [
    "ACTION_MESSAGE_ACCEPTED_EVENT",
    "ACTION_MESSAGE_ADOPTED_EVENT",
    "ActionInvalidationIdentityError",
    "ActionInvalidationEventData",
    "ActionInvalidationTransactionError",
    "append_action_invalidation_event",
]
