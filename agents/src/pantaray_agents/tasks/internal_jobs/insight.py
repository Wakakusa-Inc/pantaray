from __future__ import annotations

import asyncio

import pantaray_agents.dependencies_memory as deps
from pantaray_agents.local_runtime.context.source_control import context_source_control
from pantaray_agents.local_runtime.context.source_reader import SourceReader
from pantaray_agents.local_runtime.runtime.bootstrap import read_local_runtime_db_config
from pantaray_agents.local_runtime.runtime.short_insight import run_short_insight
from pantaray_agents.tasks.types import InsightJobPayload


async def _run_insight_job(payload: InsightJobPayload) -> None:
    db_path, timeout_ms = read_local_runtime_db_config()
    gate = context_source_control.gate
    await run_short_insight(
        db_path=db_path,
        busy_timeout_ms=timeout_ms,
        user_id=payload["user_id"],
        run_id=payload["insight_id"],
        period_start=payload["period_start"],
        period_end=payload["period_end"],
        gate=gate,
        reader=SourceReader(gate),
        agent=await deps.get_insight_agent(),
    )


def run_insight_job(payload: InsightJobPayload) -> None:
    asyncio.run(_run_insight_job(payload))
