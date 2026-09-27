from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from pantaray_agents.local_runtime.runtime import stop_barrier


def test_stop_barrier_cancels_concurrent_actions_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every in-flight Action is stopped at once, not one cleanup after another.

    Each cancel waits until all of them have started, so a sequential barrier
    never gets past the first one.
    """
    action_ids = ("action-a", "action-b", "action-c")
    monkeypatch.setattr(
        stop_barrier,
        "read_local_runtime_db_config",
        lambda: (Path("unused.db"), 1_000),
    )
    monkeypatch.setattr(
        stop_barrier, "_in_flight_action_ids", lambda **_fields: action_ids
    )

    async def run() -> list[str]:
        started: list[str] = []
        all_started = asyncio.Event()

        async def cancel(**fields: Any) -> bool:
            started.append(str(fields["action_id"]))
            if len(started) == len(action_ids):
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1.0)
            return True

        monkeypatch.setattr(stop_barrier, "execute_action_cancel", cancel)
        await stop_barrier._cancel_in_flight_actions(owner_id="owner-1")
        return started

    assert sorted(asyncio.run(run())) == sorted(action_ids)
