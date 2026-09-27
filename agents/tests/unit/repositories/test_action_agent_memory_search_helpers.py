from datetime import UTC, datetime

from pantaray_agents.repositories.action_support.memory_search_helpers import (
    generate_lookback_months,
)


def test_generate_lookback_months_excludes_current_month() -> None:
    """lookback_months は当月を含めず、完了済み過去月のみ返す。"""

    reference = datetime(2026, 3, 15, 12, 0, tzinfo=UTC)
    periods = generate_lookback_months(3, reference)

    assert periods == [
        ("2026-02-01T00:00:00+00:00", "2026-03-01T00:00:00+00:00"),
        ("2026-01-01T00:00:00+00:00", "2026-02-01T00:00:00+00:00"),
        ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
    ]


def test_generate_lookback_months_handles_year_boundary() -> None:
    """年跨ぎでも period_start/period_end を正しく生成する。"""

    reference = datetime(2026, 1, 5, 0, 0, tzinfo=UTC)
    periods = generate_lookback_months(2, reference)

    assert periods == [
        ("2025-12-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"),
        ("2025-11-01T00:00:00+00:00", "2025-12-01T00:00:00+00:00"),
    ]
