"""Caller-owned transactions for source lifecycle and cursor state.

Writes require an existing transaction and never commit. Callers must let failures
roll back the entire transition using storage.transactions.immediate_transaction.
"""

import sqlite3

from pydantic import TypeAdapter

from pantaray_agents.local_runtime.storage.transactions import (
    SQLiteTransactionOwnershipError,
)
from pantaray_agents.schema.context_source import (
    SourceBinding,
    SourceState,
    SourceTransition,
    SourceTransitionResult,
)

_STATE: TypeAdapter[SourceState] = TypeAdapter(SourceState)
_REQUEST: TypeAdapter[SourceTransition] = TypeAdapter(SourceTransition)
_RESULT: TypeAdapter[SourceTransitionResult] = TypeAdapter(SourceTransitionResult)


class ContextStoreConflict(RuntimeError):
    """An immutable identity was reused or a compare-and-swap lost."""


class ContextStoreIntegrityError(ValueError):
    """A context record's subject or durable parent does not match."""


def _writing(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise SQLiteTransactionOwnershipError("context writes require a transaction")


def get_source(connection: sqlite3.Connection, user_id: str) -> SourceState | None:
    row = connection.execute(
        "SELECT state_json FROM context_sources WHERE user_id = ?", (user_id,)
    ).fetchone()
    return None if row is None else _STATE.validate_json(row[0])


def is_capture_paused(connection: sqlite3.Connection, user_id: str) -> bool:
    """Whether this user turned recording off.

    Two states say so. A ready source that is not capturing is the pause the app
    publishes for the toggle. A source stopped with reason ``disabled`` is the
    fallback the app takes when that pause fails: it stops the recorder outright,
    which is still the same "off" and must suppress the same work. Every other
    stopped or blocked reason belongs to a recorder that is gone for a reason of
    its own, and the user's recording preference is unchanged.
    """
    state = get_source(connection, user_id)
    if state is None:
        return False
    if state.kind == "ready":
        return state.capture_paused
    return state.kind == "stopped" and state.reason == "disabled"


def compare_source(
    connection: sqlite3.Connection,
    user_id: str,
    expected: SourceState | None,
    state: SourceState,
) -> None:
    _writing(connection)
    if state.kind == "ready" and state.binding.user_id != user_id:
        raise ContextStoreIntegrityError("source belongs to another subject")
    if get_source(connection, user_id) != expected:
        raise ContextStoreConflict("source state changed")
    connection.execute(
        "INSERT INTO context_sources VALUES (?, ?) ON CONFLICT(user_id) "
        "DO UPDATE SET state_json = excluded.state_json",
        (user_id, _STATE.dump_json(state).decode()),
    )


def get_source_receipt(
    connection: sqlite3.Connection, user_id: str, request: SourceTransition
) -> SourceTransitionResult | None:
    row = connection.execute(
        "SELECT request_json, result_json FROM context_source_receipts "
        "WHERE user_id = ? AND request_id = ?",
        (user_id, str(request.request_id)),
    ).fetchone()
    if row is None:
        return None
    if _REQUEST.validate_json(row[0]) != request:
        raise ContextStoreConflict("source request ID reused")
    return _RESULT.validate_json(row[1])


def save_source_receipt(
    connection: sqlite3.Connection,
    user_id: str,
    request: SourceTransition,
    result: SourceTransitionResult,
) -> None:
    _writing(connection)
    if result.kind == "applied" and result.state.kind == "ready":
        if result.state.binding.user_id != user_id:
            raise ContextStoreIntegrityError("receipt belongs to another subject")
    existing = get_source_receipt(connection, user_id, request)
    if existing is not None:
        if existing != result:
            raise ContextStoreConflict("source result changed")
        return
    connection.execute(
        "INSERT INTO context_source_receipts VALUES (?, ?, ?, ?)",
        (
            user_id,
            str(request.request_id),
            _REQUEST.dump_json(request).decode(),
            _RESULT.dump_json(result).decode(),
        ),
    )


def _stream_key(binding: SourceBinding) -> str:
    # The cursor is a position inside the recorder store, so it must outlive the
    # permit: every restart renews the epoch, and a policy change keeps the
    # store. A replaced store answers with a reset gap instead.
    return binding.model_dump_json(exclude={"epoch", "policy_revision"})


def get_cursor(connection: sqlite3.Connection, binding: SourceBinding) -> str | None:
    row = connection.execute(
        "SELECT cursor FROM context_streams WHERE user_id = ? AND binding_json = ?",
        (binding.user_id, _stream_key(binding)),
    ).fetchone()
    return None if row is None else str(row[0])


def compare_cursor(
    connection: sqlite3.Connection,
    binding: SourceBinding,
    expected: str | None,
    cursor: str,
) -> None:
    _writing(connection)
    if get_cursor(connection, binding) != expected:
        raise ContextStoreConflict("source cursor changed")
    connection.execute(
        "INSERT INTO context_streams VALUES (?, ?, ?) "
        "ON CONFLICT(user_id, binding_json) DO UPDATE SET cursor = excluded.cursor",
        (binding.user_id, _stream_key(binding), cursor),
    )
