from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


class SQLiteTransactionOwnershipError(RuntimeError):
    pass


class SQLiteAfterCommitRegistrationError(RuntimeError):
    pass


@dataclass(slots=True)
class _CommitHookScope:
    connection_id: int
    callbacks: list[Callable[[], None]] = field(default_factory=list)


_COMMIT_HOOK_SCOPE: ContextVar[_CommitHookScope | None] = ContextVar(
    "sqlite_commit_hook_scope",
    default=None,
)


@contextmanager
def immediate_transaction(connection: sqlite3.Connection) -> Iterator[None]:
    """Own a SQLite write transaction and run registered hooks after commit."""

    if connection.in_transaction:
        raise SQLiteTransactionOwnershipError(
            "immediate transaction must own the SQLite connection"
        )
    connection.execute("BEGIN IMMEDIATE")
    scope = _CommitHookScope(connection_id=id(connection))
    token: Token[_CommitHookScope | None] = _COMMIT_HOOK_SCOPE.set(scope)
    committed_callbacks: tuple[Callable[[], None], ...] = ()
    try:
        yield
    except BaseException:
        connection.rollback()
        raise
    else:
        try:
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        committed_callbacks = tuple(scope.callbacks)
    finally:
        _COMMIT_HOOK_SCOPE.reset(token)
    _run_after_commit_callbacks(committed_callbacks)


def register_after_commit(
    *, connection: sqlite3.Connection, callback: Callable[[], None]
) -> None:
    scope = _COMMIT_HOOK_SCOPE.get()
    if scope is None or scope.connection_id != id(connection):
        raise SQLiteAfterCommitRegistrationError(
            "after-commit callback requires the owning immediate transaction"
        )
    scope.callbacks.append(callback)


def _run_after_commit_callbacks(callbacks: tuple[Callable[[], None], ...]) -> None:
    for callback in callbacks:
        try:
            callback()
        except Exception:  # noqa: BLE001 - a committed transaction cannot be undone
            logger.exception("SQLite after-commit callback failed")


__all__ = [
    "SQLiteAfterCommitRegistrationError",
    "SQLiteTransactionOwnershipError",
    "immediate_transaction",
    "register_after_commit",
]
