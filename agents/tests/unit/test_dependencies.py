import pytest

from pantaray_agents.dependencies import (
    _get_current_settings,
    get_action_repository,
    get_suggestion_repository,
)
from pantaray_agents.mock.mock_agent_repository import (
    MockActionAgentRepository,
    MockSuggestionAgentRepository,
)
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    register_active_settings_module,
)


def test_get_current_settings_loads_local_runtime_config_without_alias_import_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("SUPABASE_SECRET_KEY", raising=False)
    clear_active_settings_module()
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)

    settings = _get_current_settings()

    assert settings["mode"] == "local_runtime"
    assert "supabase_auth_key" not in settings


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("get_repository", "expected_type"),
    [
        (get_action_repository, MockActionAgentRepository),
        (get_suggestion_repository, MockSuggestionAgentRepository),
    ],
)
async def test_mock_mode_selects_matching_repository(
    monkeypatch: pytest.MonkeyPatch,
    get_repository,
    expected_type,
) -> None:
    monkeypatch.setattr(
        "pantaray_agents.dependencies._get_current_settings",
        lambda: {"use_mocks": True},
    )

    assert isinstance(await get_repository(), expected_type)
