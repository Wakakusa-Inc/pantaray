"""Activity summary generation wrappers."""

from __future__ import annotations

import asyncio

from pantaray_agents.local_runtime.runtime.activity_summary_scheduler import (
    SummaryType,
    run_summary_generation,
)


async def _run_summary_generation(
    summary_type: SummaryType,
) -> dict[str, int]:
    return await run_summary_generation(summary_type)


def generate_hourly_summary() -> dict[str, int]:
    """1時間サマリ生成ジョブを enqueue する。"""
    return asyncio.run(_run_summary_generation("1h"))


def generate_daily_summary() -> dict[str, int]:
    """24時間サマリ生成ジョブを enqueue する。"""
    return asyncio.run(_run_summary_generation("24h"))


def generate_weekly_summary() -> dict[str, int]:
    """1週間サマリ生成ジョブを enqueue する。"""
    return asyncio.run(_run_summary_generation("1w"))


def generate_monthly_summary() -> dict[str, int]:
    """1ヶ月サマリ生成ジョブを enqueue する。"""
    return asyncio.run(_run_summary_generation("1m"))


def generate_quarterly_summary() -> dict[str, int]:
    """3ヶ月サマリ生成ジョブを enqueue する。"""
    return asyncio.run(_run_summary_generation("3m"))


__all__ = [
    "generate_hourly_summary",
    "generate_daily_summary",
    "generate_weekly_summary",
    "generate_monthly_summary",
    "generate_quarterly_summary",
]
