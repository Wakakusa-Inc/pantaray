"""WS オーケストレーション向けの観測性・ループ抑止ユーティリティ。

目的:
    - 例外の握りつぶしによる「同じ失敗を叩き続ける」状態を抑止する。
    - ログを過剰に汚染せず、必要な情報だけを一定間隔で出力できるようにする。

方針:
    - 失敗は黙殺せず、メトリクス/ログに残す（ただしログは rate limit）。
    - 依存が壊れている状態での再試行を抑制するため、簡易 circuit breaker を提供する。
"""

from __future__ import annotations

import time
from dataclasses import dataclass


def now_monotonic_seconds() -> float:
    """単調増加クロック秒を返す（テストで monkeypatch しやすいラッパー）。"""

    return time.monotonic()


class RateLimiter:
    """キー単位でログ出力頻度を制限する。

    例:
        limiter = RateLimiter()
        if limiter.should_log("suggestion_repository:load", interval_seconds=60):
            logger.exception(...)
    """

    def __init__(self) -> None:
        self._last_logged_at: dict[str, float] = {}

    def should_log(
        self,
        key: str,
        *,
        interval_seconds: float,
        now_seconds: float | None = None,
    ) -> bool:
        """ログを出してよいか判定する。

        Args:
            key: 抑制キー
            interval_seconds: 同一キーでログを許可する最小間隔（秒）
            now_seconds: 現在時刻（単調増加秒）。未指定なら `now_monotonic_seconds()` を使う。
        """

        if interval_seconds <= 0:
            # 0以下は抑制しない（呼び出し側の意図を優先）
            return True
        now = now_seconds if now_seconds is not None else now_monotonic_seconds()
        last = self._last_logged_at.get(key)
        if last is None or (now - last) >= float(interval_seconds):
            self._last_logged_at[key] = now
            return True
        return False


@dataclass
class CircuitState:
    consecutive_failures: int = 0
    open_until_seconds: float = 0.0


class CircuitBreaker:
    """連続失敗が一定回数を超えた依存呼び出しを一時的に抑止する。"""

    def __init__(
        self,
        *,
        failure_threshold: int,
        open_interval_seconds: float,
    ) -> None:
        if failure_threshold <= 0:
            raise ValueError("failure_threshold must be > 0")
        if open_interval_seconds <= 0:
            raise ValueError("open_interval_seconds must be > 0")
        self._failure_threshold = int(failure_threshold)
        self._open_interval_seconds = float(open_interval_seconds)
        self._state_by_key: dict[str, CircuitState] = {}

    def is_open(self, key: str, *, now_seconds: float | None = None) -> bool:
        now = now_seconds if now_seconds is not None else now_monotonic_seconds()
        st = self._state_by_key.get(key)
        if st is None:
            return False
        return now < float(st.open_until_seconds)

    def allow(self, key: str, *, now_seconds: float | None = None) -> bool:
        """呼び出しを許可するかを返す。"""

        return not self.is_open(key, now_seconds=now_seconds)

    def record_success(self, key: str) -> None:
        st = self._state_by_key.get(key)
        if st is None:
            return
        st.consecutive_failures = 0
        st.open_until_seconds = 0.0

    def record_failure(self, key: str, *, now_seconds: float | None = None) -> bool:
        """失敗を記録し、circuit を open した場合は True を返す。"""

        now = now_seconds if now_seconds is not None else now_monotonic_seconds()
        st = self._state_by_key.get(key)
        if st is None:
            st = CircuitState()
            self._state_by_key[key] = st
        st.consecutive_failures += 1
        if st.consecutive_failures >= self._failure_threshold:
            st.open_until_seconds = now + self._open_interval_seconds
            return True
        return False

    def reset(self) -> None:
        """全キーの状態をリセットする（テスト用）。"""

        self._state_by_key.clear()
