"""Terminal retry backoff during a long child settlement wait."""

from __future__ import annotations

from pantaray_agents.tasks.action_job_support import terminal_retry_delay_seconds


def test_retry_delay_survives_a_four_digit_child_settlement_wait() -> None:
    """A capped delay must not expand an unbounded integer power first."""

    assert terminal_retry_delay_seconds(consecutive_failures=1) == 1.0
    assert terminal_retry_delay_seconds(consecutive_failures=1025) == 10.0
