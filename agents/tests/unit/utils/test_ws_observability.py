from __future__ import annotations

import pytest

from pantaray_agents.utils.ws_observability import CircuitBreaker, RateLimiter


def test_rate_limiter_should_log_by_interval() -> None:
    limiter = RateLimiter()
    assert limiter.should_log("k", interval_seconds=10.0, now_seconds=100.0) is True
    # interval 内は抑制される
    assert limiter.should_log("k", interval_seconds=10.0, now_seconds=109.9) is False
    # interval 経過で再度許可
    assert limiter.should_log("k", interval_seconds=10.0, now_seconds=110.0) is True


def test_circuit_breaker_opens_after_threshold_and_allows_after_reset() -> None:
    cb = CircuitBreaker(failure_threshold=2, open_interval_seconds=30.0)
    key = "dep:op"

    assert cb.allow(key, now_seconds=1.0) is True
    opened = cb.record_failure(key, now_seconds=1.0)
    assert opened is False
    assert cb.allow(key, now_seconds=1.0) is True

    opened = cb.record_failure(key, now_seconds=2.0)
    assert opened is True
    assert cb.is_open(key, now_seconds=2.0) is True
    assert cb.allow(key, now_seconds=2.0) is False

    # open 期間が過ぎれば allow になる（ただし連続失敗数は残る）
    assert cb.allow(key, now_seconds=40.0) is True
    # success で状態がクリアされる
    cb.record_success(key)
    assert cb.is_open(key, now_seconds=40.0) is False


def test_circuit_breaker_validation() -> None:
    with pytest.raises(ValueError):
        _ = CircuitBreaker(failure_threshold=0, open_interval_seconds=10.0)
    with pytest.raises(ValueError):
        _ = CircuitBreaker(failure_threshold=1, open_interval_seconds=0.0)
