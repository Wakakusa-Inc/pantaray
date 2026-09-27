"""action_step 永続化の共通リトライヘルパー。"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol

from pantaray_agents.agents.action_agent.runtime.log_safety import (
    exception_type_name,
)
from pantaray_agents.schema.repositories.repository import RepositoryErrorKind
from pantaray_agents.schema.repository_errors import (
    SupportsRepositoryFailure,
    classify_repository_exception,
    is_retryable_repository_result,
)

logger = logging.getLogger(__name__)

# save_action_step の再試行上限（合計試行回数）
ACTION_STEP_PERSISTENCE_MAX_ATTEMPTS = 3
# 再試行までの初期待機秒数（seconds）
ACTION_STEP_PERSISTENCE_INITIAL_DELAY_SECONDS = 0.05
# 再試行ごとの待機時間倍率（指数バックオフ）
ACTION_STEP_PERSISTENCE_BACKOFF_MULTIPLIER = 2.0


class ActionStepPersistenceError(RuntimeError):
    """action_step 永続化に失敗したことを示す例外。"""


@dataclass(frozen=True, slots=True)
class ActionStepPersistenceRetryPolicy:
    """action_step 永続化の再試行ポリシー。"""

    max_attempts: int = ACTION_STEP_PERSISTENCE_MAX_ATTEMPTS
    initial_delay_seconds: float = ACTION_STEP_PERSISTENCE_INITIAL_DELAY_SECONDS
    backoff_multiplier: float = ACTION_STEP_PERSISTENCE_BACKOFF_MULTIPLIER


DEFAULT_ACTION_STEP_PERSISTENCE_RETRY_POLICY = ActionStepPersistenceRetryPolicy()


class SupportsRepositoryError(SupportsRepositoryFailure, Protocol):
    """`error` 属性を持つ RepositoryResult 互換型。"""

    @property
    def error(self) -> str | Exception | None: ...


def _extract_exception_message(exc: Exception) -> str:
    text = str(exc).strip()
    return text if text else exc.__class__.__name__


def extract_repository_error_message(result: SupportsRepositoryError) -> str | None:
    """RepositoryResult 風オブジェクトからエラーメッセージを抽出する。"""
    raw_error = result.error
    if isinstance(raw_error, Exception):
        text = str(raw_error).strip()
        return text if text else raw_error.__class__.__name__
    if isinstance(raw_error, str):
        text = raw_error.strip()
        return text if text else None
    return None


async def save_action_step_with_retry[TRepositoryResult: SupportsRepositoryError](
    *,
    save_once: Callable[[], Awaitable[TRepositoryResult]],
    step_name: str,
    step_id: str,
    retry_policy: ActionStepPersistenceRetryPolicy = DEFAULT_ACTION_STEP_PERSISTENCE_RETRY_POLICY,
    log: logging.Logger | None = None,
) -> TRepositoryResult:
    """save_action_step 相当の処理を指数バックオフ付きで実行する。"""
    delay_seconds = retry_policy.initial_delay_seconds
    attempts_used = 0
    last_error_message = "unknown"
    last_error_kind = "unknown"
    last_retryable = True
    use_logger = log or logger

    for attempt in range(1, retry_policy.max_attempts + 1):
        attempts_used = attempt
        try:
            result = await save_once()
        except Exception as exc:  # noqa: BLE001  # pylint: disable=broad-exception-caught
            classification = classify_repository_exception(exc)
            last_error_message = _extract_exception_message(exc)
            last_error_kind = (
                classification.error_kind.value
                if classification.error_kind is not RepositoryErrorKind.UNKNOWN
                else exception_type_name(exc)
            )
            last_retryable = classification.retryable
        else:
            error_message = extract_repository_error_message(result)
            if error_message is None:
                return result
            last_error_message = error_message
            last_error_kind = "repository_error"
            retryable = is_retryable_repository_result(result)
            if not isinstance(retryable, bool):
                raise ActionStepPersistenceError(
                    "RepositoryResult must provide structured retry semantics: "
                    f"step_name={step_name} step_id={step_id} error={error_message}"
                )
            last_retryable = retryable

        is_last_attempt = attempt >= retry_policy.max_attempts
        if is_last_attempt or not last_retryable:
            break

        use_logger.warning(
            "Retrying save_action_step "
            "(attempt=%d/%d delay_seconds=%.2f step_name=%s step_id=%s error_kind=%s retryable=%s)",
            attempt,
            retry_policy.max_attempts,
            delay_seconds,
            step_name,
            step_id,
            last_error_kind,
            last_retryable,
        )
        await asyncio.sleep(delay_seconds)
        delay_seconds *= retry_policy.backoff_multiplier

    raise ActionStepPersistenceError(
        "Failed to persist action step: "
        f"step_name={step_name} step_id={step_id} attempts={attempts_used} "
        f"retryable={last_retryable} error={last_error_message}"
    )


__all__ = [
    "ActionStepPersistenceError",
    "ActionStepPersistenceRetryPolicy",
    "classify_repository_exception",
    "DEFAULT_ACTION_STEP_PERSISTENCE_RETRY_POLICY",
    "extract_repository_error_message",
    "is_retryable_repository_result",
    "save_action_step_with_retry",
]
