from __future__ import annotations

import pytest


@pytest.mark.asyncio
async def test_run_summary_generation_targets_the_current_owner(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A summary with no explicit user is enqueued for whoever owns the data now."""

    from pantaray_agents.local_runtime.runtime import activity_summary_scheduler
    from pantaray_agents.tasks.activity_job import _run_summary_generation

    enqueued_for: list[str] = []
    monkeypatch.setattr(
        activity_summary_scheduler, "current_owner_id", lambda: "local-owner"
    )
    monkeypatch.setattr(
        activity_summary_scheduler,
        "enqueue_activity_summary_job",
        lambda **kwargs: enqueued_for.append(str(kwargs["user_id"])),
    )

    result = await _run_summary_generation("24h")

    assert enqueued_for == ["local-owner"]
    assert result == {"total": 1, "enqueued": 1, "failed": 0}
