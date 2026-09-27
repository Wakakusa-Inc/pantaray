"""トレースコンテキスト管理ユーティリティ。

ActionAgent の実行中に action_id, goal_handle などの
トレース情報をコンテキストとして保持し、ログに自動的に含めるための仕組みを提供する。
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextvars import ContextVar
from dataclasses import dataclass, field
from types import TracebackType
from typing import TypedDict

# コンテキスト変数（スレッド/コルーチンごとに独立した値を保持）
_trace_context: ContextVar[TraceContext | None] = ContextVar(
    "trace_context", default=None
)


@dataclass
class TraceContext:
    """トレース情報を保持するデータクラス。"""

    action_id: str | None = None
    request_id: str | None = None
    local_job_id: str | None = None
    goal_handle: str | None = None
    step_id: str | None = None
    user_id: str | None = None
    suggestion_id: str | None = None
    extra: dict[str, object] = field(default_factory=dict)

    def to_dict(self) -> dict[str, object]:
        """ログ出力用の辞書を生成する。

        None でない値のみを含める。
        """
        result: dict[str, object] = {}
        if self.action_id:
            result["action_id"] = self.action_id
        if self.request_id:
            result["request_id"] = self.request_id
        if self.local_job_id:
            result["local_job_id"] = self.local_job_id
        if self.goal_handle:
            result["goal_handle"] = self.goal_handle
        if self.step_id:
            result["step_id"] = self.step_id
        if self.user_id:
            result["user_id"] = self.user_id
        if self.suggestion_id:
            result["suggestion_id"] = self.suggestion_id
        if self.extra:
            result.update(self.extra)
        return result

    def copy(self, **updates: object) -> TraceContext:
        """現在のコンテキストをコピーして一部を更新する。

        注意:
            呼び出し側が `**kwargs` で動的入力を渡す都合上、ここでは受け取った値を
            型安全に正規化したうえで適用する。
        """
        sanitized = _sanitize_trace_kwargs(updates)
        extra_updates: dict[str, object] = dict(sanitized.get("extra") or {})
        return TraceContext(
            action_id=sanitized.get("action_id", self.action_id),
            request_id=sanitized.get("request_id", self.request_id),
            local_job_id=sanitized.get("local_job_id", self.local_job_id),
            goal_handle=sanitized.get("goal_handle", self.goal_handle),
            step_id=sanitized.get("step_id", self.step_id),
            user_id=sanitized.get("user_id", self.user_id),
            suggestion_id=sanitized.get("suggestion_id", self.suggestion_id),
            extra={**self.extra, **extra_updates},
        )


class TraceContextKwargs(TypedDict, total=False):
    """TraceContext の更新/生成に使用できるキーワード引数の型。

    目的:
        `TraceContextManager(**kwargs)` のような動的キーワード入力を受けつつ、
        mypy 的に安全な型（str|None と dict[str, object]）へ正規化するための契約。
    """

    action_id: str | None
    request_id: str | None
    local_job_id: str | None
    goal_handle: str | None
    step_id: str | None
    user_id: str | None
    suggestion_id: str | None
    extra: dict[str, object]


def _coerce_optional_str(value: object) -> str | None:
    """任意の値を `str | None` に正規化する（型安全な範囲でのみ許可）。"""
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        return normalized or None
    return None


def _sanitize_trace_kwargs(raw: Mapping[str, object]) -> TraceContextKwargs:
    """TraceContext 用の kwargs を型安全に正規化する。

    - 受け付けるキー以外は破棄する（ログ汚染防止 / 型安全性の確保）。
    - str フィールドは非空文字列のみ採用する。
    - None/空文字は「既存値を消す」ではなく「更新なし」として扱う。
    - extra は mapping のみ許可し、dict[str, object] として取り込む。
    """
    out: TraceContextKwargs = {}
    for k, v in raw.items():
        if k == "action_id":
            if coerced := _coerce_optional_str(v):
                out["action_id"] = coerced
            continue
        if k == "request_id":
            if coerced := _coerce_optional_str(v):
                out["request_id"] = coerced
            continue
        if k == "local_job_id":
            if coerced := _coerce_optional_str(v):
                out["local_job_id"] = coerced
            continue
        if k == "goal_handle":
            if coerced := _coerce_optional_str(v):
                out["goal_handle"] = coerced
            continue
        if k == "step_id":
            if coerced := _coerce_optional_str(v):
                out["step_id"] = coerced
            continue
        if k == "user_id":
            if coerced := _coerce_optional_str(v):
                out["user_id"] = coerced
            continue
        if k == "suggestion_id":
            if coerced := _coerce_optional_str(v):
                out["suggestion_id"] = coerced
            continue
        if k == "extra":
            if isinstance(v, Mapping):
                out["extra"] = dict(v)
            continue
    return out


def get_trace_context() -> TraceContext | None:
    """現在のトレースコンテキストを取得する。"""
    return _trace_context.get()


def set_trace_context(ctx: TraceContext | None) -> None:
    """トレースコンテキストを設定する。"""
    _trace_context.set(ctx)


class TraceContextManager:
    """トレースコンテキストをスコープ管理するコンテキストマネージャ。

    使用例:
        with TraceContextManager(action_id="xxx", goal_handle="G1"):
            logger.info("Processing goal")  # ログにトレース情報が含まれる
    """

    def __init__(self, **kwargs: object) -> None:
        """コンテキストを初期化する。

        Args:
            **kwargs: TraceContext のフィールドに対応するキーワード引数
        """
        self._kwargs: TraceContextKwargs = _sanitize_trace_kwargs(kwargs)
        self._previous: TraceContext | None = None

    def __enter__(self) -> TraceContext:
        """コンテキストに入る。"""
        self._previous = get_trace_context()
        if self._previous:
            new_ctx = self._previous.copy(**self._kwargs)
        else:
            new_ctx = TraceContext(**self._kwargs)
        set_trace_context(new_ctx)
        return new_ctx

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        """コンテキストから出る。"""
        set_trace_context(self._previous)


class TraceContextFilter(logging.Filter):
    """ログレコードにトレースコンテキスト情報を追加するフィルタ。

    使用例:
        handler = logging.StreamHandler()
        handler.addFilter(TraceContextFilter())
        logger.addHandler(handler)
    """

    def filter(self, record: logging.LogRecord) -> bool:
        """ログレコードにトレース情報を追加する。"""
        ctx = get_trace_context()
        if ctx:
            trace_dict = ctx.to_dict()
            for key, value in trace_dict.items():
                setattr(record, key, value)
            # 複合キー（CloudWatch Logs Insights でのクエリ用）
            record.trace_ids = " ".join(f"{k}={v}" for k, v in trace_dict.items())
        else:
            record.trace_ids = ""
        return True


def configure_trace_logging(logger_name: str | None = None) -> None:
    """指定したロガーにトレースコンテキストフィルタを追加する。

    Args:
        logger_name: ロガー名（None の場合はルートロガー）
    """
    target_logger = logging.getLogger(logger_name)
    trace_filter = TraceContextFilter()

    # 既存のハンドラにフィルタを追加
    for handler in target_logger.handlers:
        handler.addFilter(trace_filter)

    # ルートロガーのハンドラにも追加（伝播する場合）
    if logger_name and target_logger.propagate:
        for handler in logging.getLogger().handlers:
            # 重複追加を避ける
            if not any(isinstance(f, TraceContextFilter) for f in handler.filters):
                handler.addFilter(trace_filter)


__all__ = [
    "TraceContext",
    "TraceContextManager",
    "TraceContextFilter",
    "get_trace_context",
    "set_trace_context",
    "configure_trace_logging",
]
