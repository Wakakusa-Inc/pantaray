from __future__ import annotations

from collections.abc import Callable
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from types import TracebackType


@dataclass(frozen=True, slots=True)
class LocalRuntimeDbExecutionContext:
    db_path: Path
    busy_timeout_ms: int


_LOCAL_RUNTIME_DB_CONTEXT: ContextVar[LocalRuntimeDbExecutionContext | None] = (
    ContextVar("pantaray_local_runtime_db_execution_context", default=None)
)


@dataclass(slots=True)
class _LocalRuntimeDbExecutionContextBinding:
    db_path: Path
    busy_timeout_ms: int
    _token: Token[LocalRuntimeDbExecutionContext | None] | None = None

    def __enter__(self) -> None:
        self._token = _LOCAL_RUNTIME_DB_CONTEXT.set(
            LocalRuntimeDbExecutionContext(
                db_path=self.db_path,
                busy_timeout_ms=self.busy_timeout_ms,
            )
        )
        return None

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        del exc_type, exc, traceback
        assert self._token is not None
        _LOCAL_RUNTIME_DB_CONTEXT.reset(self._token)
        self._token = None
        return False


def get_local_runtime_db_execution_context() -> LocalRuntimeDbExecutionContext | None:
    return _LOCAL_RUNTIME_DB_CONTEXT.get()


def bind_local_runtime_db_execution_context(
    *,
    db_path: Path,
    busy_timeout_ms: int,
) -> _LocalRuntimeDbExecutionContextBinding:
    return _LocalRuntimeDbExecutionContextBinding(
        db_path=db_path,
        busy_timeout_ms=busy_timeout_ms,
    )


def resolve_local_runtime_db_config(
    *,
    fallback: Callable[[], tuple[Path, int]],
) -> tuple[Path, int]:
    context = get_local_runtime_db_execution_context()
    if context is not None:
        return context.db_path, context.busy_timeout_ms
    return fallback()


__all__ = [
    "LocalRuntimeDbExecutionContext",
    "bind_local_runtime_db_execution_context",
    "get_local_runtime_db_execution_context",
    "resolve_local_runtime_db_config",
]
