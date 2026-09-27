"""Repository/Agent 跨ぎで使うステージ例外型。

設計:
    - 取得（fetch）/保存（save）/Storage反映（storage）を例外型で表現する。
    - 定義は共通層（schema）に配置し、Repository 層と Agent 層の依存方向を分離する。
"""

from __future__ import annotations

import errno
import sqlite3
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable

from pantaray_agents.schema.repositories.repository import (
    RepositoryErrorKind,
    RepositoryResult,
)
from pantaray_llm.errors.exceptions import LlmProxyExecutionError

RepositoryStage = Literal["fetch", "save", "storage"]

_RETRYABLE_SQLITE_OPERATIONAL_ERROR_HINTS = (
    "database is locked",
    "database schema is locked",
    "database table is locked",
    "database busy",
)
_RETRYABLE_OS_ERROR_NUMBERS = frozenset(
    {
        errno.EAGAIN,
        errno.EBUSY,
        errno.EIO,
        errno.EINTR,
        errno.EMFILE,
        errno.ENFILE,
        errno.ENOSPC,
        errno.ETIMEDOUT,
    }
)


class AgentRepositoryError(RuntimeError):
    """Repository 層の失敗を表す共通例外（ステージ情報付き）。"""

    def __init__(
        self,
        *,
        stage: RepositoryStage,
        safe_message: str,
        error_kind: RepositoryErrorKind | None = None,
        retryable: bool | None = None,
    ) -> None:
        if not isinstance(safe_message, str) or not safe_message.strip():
            raise ValueError("safe_message must be a non-empty string")
        super().__init__(safe_message)
        self.stage = stage
        self.safe_message = safe_message
        self.error_kind = error_kind
        self.retryable = retryable


class FetchContextError(AgentRepositoryError):
    """コンテキスト取得（DB/外部API）の失敗を表す例外。"""

    def __init__(
        self,
        safe_message: str,
        *,
        error_kind: RepositoryErrorKind | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(
            stage="fetch",
            safe_message=safe_message,
            error_kind=error_kind,
            retryable=retryable,
        )


class SaveResponseError(AgentRepositoryError):
    """レスポンス永続化（DB更新など）の失敗を表す例外。"""

    def __init__(self, safe_message: str) -> None:
        super().__init__(stage="save", safe_message=safe_message)


class StorageCommitError(AgentRepositoryError):
    """Storage 反映（アップロード/更新）の失敗を表す例外。"""

    def __init__(self, safe_message: str) -> None:
        super().__init__(stage="storage", safe_message=safe_message)


@dataclass(frozen=True, slots=True)
class RepositoryExceptionClassification:
    """Repository boundary failure classification used by retry state machines."""

    error_kind: RepositoryErrorKind
    retryable: bool


@runtime_checkable
class SupportsRepositoryFailure(Protocol):
    error_kind: RepositoryErrorKind | None
    retryable: bool | None


def classify_repository_exception(
    exc: BaseException,
) -> RepositoryExceptionClassification:
    """Classify only explicitly known transient failures as retryable."""

    if isinstance(exc, AgentRepositoryError):
        return RepositoryExceptionClassification(
            error_kind=exc.error_kind or RepositoryErrorKind.UNKNOWN,
            retryable=exc.retryable is True,
        )
    if isinstance(exc, LlmProxyExecutionError):
        return RepositoryExceptionClassification(
            error_kind=(
                RepositoryErrorKind.TRANSIENT
                if exc.retryable
                else RepositoryErrorKind.UNKNOWN
            ),
            retryable=exc.retryable,
        )
    if isinstance(exc, SupportsRepositoryFailure):
        error_kind = exc.error_kind
        retryable = exc.retryable
        if isinstance(error_kind, RepositoryErrorKind) and isinstance(retryable, bool):
            return RepositoryExceptionClassification(
                error_kind=error_kind,
                retryable=retryable,
            )
    if isinstance(exc, sqlite3.IntegrityError):
        normalized = _exception_message(exc).lower()
        return RepositoryExceptionClassification(
            error_kind=(
                RepositoryErrorKind.CONFLICT
                if "unique constraint failed" in normalized
                else RepositoryErrorKind.CONSTRAINT
            ),
            retryable=False,
        )
    if isinstance(exc, sqlite3.OperationalError):
        normalized = _exception_message(exc).lower()
        retryable = any(
            hint in normalized for hint in _RETRYABLE_SQLITE_OPERATIONAL_ERROR_HINTS
        )
        return RepositoryExceptionClassification(
            error_kind=(
                RepositoryErrorKind.TRANSIENT
                if retryable
                else RepositoryErrorKind.UNKNOWN
            ),
            retryable=retryable,
        )
    if isinstance(exc, OSError) and exc.errno in _RETRYABLE_OS_ERROR_NUMBERS:
        return RepositoryExceptionClassification(
            error_kind=RepositoryErrorKind.TRANSIENT,
            retryable=True,
        )
    return RepositoryExceptionClassification(
        error_kind=RepositoryErrorKind.UNKNOWN,
        retryable=False,
    )


def is_retryable_repository_exception(exc: BaseException) -> bool:
    return classify_repository_exception(exc).retryable


def is_retryable_repository_result(
    result: SupportsRepositoryFailure,
) -> bool | None:
    """Read structured retry semantics without guessing from error text."""
    if isinstance(result.retryable, bool):
        return result.retryable
    if result.error_kind is RepositoryErrorKind.TRANSIENT:
        return True
    if result.error_kind in {
        RepositoryErrorKind.VALIDATION,
        RepositoryErrorKind.AUTHORIZATION,
        RepositoryErrorKind.NOT_FOUND,
        RepositoryErrorKind.CONSTRAINT,
        RepositoryErrorKind.CONFLICT,
    }:
        return False
    return None


def _exception_message(exc: BaseException) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__


def repository_data_or_raise[T](
    result: RepositoryResult[T],
    *,
    safe_message: str,
) -> T | None:
    """Return repository data while preserving explicit failure semantics."""

    if result.error is not None:
        raise FetchContextError(
            safe_message,
            error_kind=result.error_kind,
            retryable=is_retryable_repository_result(result),
        )
    return result.data


__all__ = [
    "AgentRepositoryError",
    "classify_repository_exception",
    "FetchContextError",
    "is_retryable_repository_exception",
    "is_retryable_repository_result",
    "RepositoryExceptionClassification",
    "SaveResponseError",
    "StorageCommitError",
    "SupportsRepositoryFailure",
    "RepositoryStage",
    "repository_data_or_raise",
]
