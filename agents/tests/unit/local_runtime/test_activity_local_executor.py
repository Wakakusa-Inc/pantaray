from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from pantaray_agents.local_runtime.runtime.activity_local_executor import (
    ActivitySummaryExecutionResult,
    _build_activity_agent_config,
    _load_current_settings,
    run_local_activity_summary_agent,
)
from pantaray_agents.schema.agent.activity import (
    ActivitySummaryAgentRequest,
    ActivitySummaryAgentResponse,
)
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    register_active_settings_module,
)


@pytest.fixture(autouse=True)
def _register_local_runtime_settings() -> None:
    clear_active_settings_module()
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)
    try:
        yield
    finally:
        clear_active_settings_module()


@pytest.mark.asyncio
async def test_build_activity_agent_config_stays_local(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.activity_local_executor.deps.get_llm_client",
        lambda: MagicMock(),
    )

    config = await _build_activity_agent_config()

    assert config["mode"] == "local_runtime"
    assert "token_wallet_repository" not in config


def test_load_current_settings_uses_local_runtime_config() -> None:
    settings = _load_current_settings()

    assert settings["mode"] == "local_runtime"
    assert "supabase_auth_key" not in settings


@pytest.mark.asyncio
async def test_run_local_activity_summary_agent_uses_run_without_persistence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = ActivitySummaryAgentResponse(
        summary_id="summary-1",
        user_id="user-1",
        summary_type="24h",
        summary="summary",
        thinking=None,
        period_start="2026-04-07T10:00:00Z",
        period_end="2026-04-08T10:00:00Z",
        source_ids=[],
        created_at="2026-04-08T10:08:34Z",
        status="success",
        error=None,
    )
    agent = MagicMock()
    agent.run_without_persistence = AsyncMock(return_value=expected)
    agent.last_prompt_text = "prompt"
    monkeypatch.setattr(
        "pantaray_agents.local_runtime.runtime.activity_local_executor._build_activity_summary_agent",
        AsyncMock(return_value=agent),
    )

    response = await run_local_activity_summary_agent(
        request=ActivitySummaryAgentRequest(
            user_id="user-1",
            summary_id="summary-1",
            summary_type="24h",
            period_start="2026-04-07T10:00:00Z",
            period_end="2026-04-08T10:00:00Z",
        ),
        db_path="/tmp/runtime.db",
        busy_timeout_ms=1_000,
    )

    assert response == ActivitySummaryExecutionResult(
        response=expected,
        prompt_text="prompt",
    )
    agent.run_without_persistence.assert_awaited_once()
