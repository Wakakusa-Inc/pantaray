"""上位サマリの source 選択が「活動なし」の下位サマリを外すことを確かめる。

ActivitySummaryAgent は source が0件の期間に `NO_ACTIVITY_TEMPLATE` を
`source_ids` 空で書く。その行を上位サマリの source に含めると、中身のない
定型文だけを LLM に渡したうえで `source_ids` 非空の成功行を書いてしまう。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tests.activity_log_seed import seed_activity_log

from pantaray_agents.agents.activity_summary_agent.agent import NO_ACTIVITY_TEMPLATE
from pantaray_agents.local_runtime.runtime.activity_local_repository import (
    SQLiteActivityRuntimeRepository,
)
from pantaray_agents.local_runtime.runtime.activity_source_rows import (
    ACTIVITY_SUMMARY_PROMPT_NAME,
    ACTIVITY_SUMMARY_PROMPT_VERSION,
    persist_activity_summary_result,
    reserve_activity_summary_processing,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database

_USER = "user-1"
_BUSY_TIMEOUT_MS = 1_000
_DAY_START = "2026-09-13T00:00:00Z"
_DAY_END = "2026-09-14T00:00:00Z"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    return path


def _seed_hourly_summary(
    db_path: Path,
    *,
    summary_id: str,
    period_start: str,
    period_end: str,
    summary: str,
    source_ids: list[str],
) -> None:
    """1h サマリを runtime と同じ writer で書き込む。"""
    for log_id in source_ids:
        seed_activity_log(
            db_path,
            log_id=log_id,
            user_id=_USER,
            period_start=period_start,
            period_end=period_end,
        )
    reserve_activity_summary_processing(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        summary_id=summary_id,
        user_id=_USER,
        summary_type="1h",
        period_start=period_start,
        period_end=period_end,
        created_at=period_end,
    )
    persist_activity_summary_result(
        db_path=db_path,
        busy_timeout_ms=_BUSY_TIMEOUT_MS,
        summary_id=summary_id,
        user_id=_USER,
        summary_type="1h",
        period_start=period_start,
        period_end=period_end,
        summary=summary,
        status="success",
        error=None,
        prompt_text="prompt",
        thinking=None,
        source_ids=source_ids,
        updated_at=period_end,
    )


def _seed_empty_hourly_summary(
    db_path: Path, *, summary_id: str, period_start: str, period_end: str
) -> None:
    _seed_hourly_summary(
        db_path,
        summary_id=summary_id,
        period_start=period_start,
        period_end=period_end,
        summary=NO_ACTIVITY_TEMPLATE.format(
            summary_type="1h",
            period_start=period_start,
            period_end=period_end,
        ),
        source_ids=[],
    )


async def _daily_sources(db_path: Path) -> list[str]:
    repository = SQLiteActivityRuntimeRepository(
        db_path=db_path, busy_timeout_ms=_BUSY_TIMEOUT_MS
    )
    result = await repository.get_source_data_for_summary(
        user_id=_USER,
        summary_type="24h",
        period_start=_DAY_START,
        period_end=_DAY_END,
        prompt_name=ACTIVITY_SUMMARY_PROMPT_NAME,
        prompt_version=ACTIVITY_SUMMARY_PROMPT_VERSION,
    )
    assert result.data is not None
    return [str(row["summary_id"]) for row in result.data]


async def test_empty_hourly_summaries_are_not_sources_for_the_daily_summary(
    db_path: Path,
) -> None:
    _seed_empty_hourly_summary(
        db_path,
        summary_id="sum-1h-empty",
        period_start="2026-09-13T01:00:00Z",
        period_end="2026-09-13T02:00:00Z",
    )
    _seed_hourly_summary(
        db_path,
        summary_id="sum-1h-active",
        period_start="2026-09-13T09:00:00Z",
        period_end="2026-09-13T10:00:00Z",
        summary="Reviewed the parser bug and wrote a regression test.",
        source_ids=["log-active"],
    )

    assert await _daily_sources(db_path) == ["sum-1h-active"]


async def test_a_day_of_only_empty_hourly_summaries_has_no_sources(
    db_path: Path,
) -> None:
    for hour in range(3):
        _seed_empty_hourly_summary(
            db_path,
            summary_id=f"sum-1h-empty-{hour}",
            period_start=f"2026-09-13T0{hour}:00:00Z",
            period_end=f"2026-09-13T0{hour + 1}:00:00Z",
        )

    assert await _daily_sources(db_path) == []
