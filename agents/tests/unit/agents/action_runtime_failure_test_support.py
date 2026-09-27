from __future__ import annotations

import os
from pathlib import Path
from typing import Literal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from tests.unit.agents.action_agent.fixtures import (
    build_action_request,
    create_local_runtime_db,
    install_local_runtime_env,
)
from tests.unit.local_runtime.action_seed import insert_agent_action

from pantaray_agents.agents.action_agent import ActionAgent
from pantaray_agents.application.action.use_case_service import (
    ActionUseCaseDeps,
    ActionUseCaseService,
)
from pantaray_agents.mock.mock_agent_repository import MockActionAgentRepository
from pantaray_agents.mock.mock_llm_client import MockLLMClient
from pantaray_agents.schema.agent.action import ActionAgentRequest
from pantaray_agents.schema.repositories.repository import RepositoryResult
from pantaray_agents.utils.prompt_loader import PromptConfig


def fake_load_config(prompt_name: str) -> PromptConfig:
    if prompt_name == "action/executing":
        return PromptConfig(prompt="{current_time}", system_instruction="SYS")
    return PromptConfig(prompt="{current_time}", system_instruction="SYS")


def install_local_runtime_test_db(
    monkeypatch: pytest.MonkeyPatch,
    *,
    tmp_path,
) -> None:
    db_path = create_local_runtime_db(db_path=tmp_path / "runtime.db")
    install_local_runtime_env(monkeypatch=monkeypatch, db_path=db_path)


def build_repo(
    *,
    action_id: str,
    suggestion_id: str,
    user_id: str,
) -> MagicMock:
    local_db_path = os.environ.get("LOCAL_DB_PATH")
    if local_db_path:
        insert_agent_action(
            db_path=Path(local_db_path),
            user_id=user_id,
            suggestion_id=suggestion_id,
            action_id=action_id,
        )
    repo = MagicMock()
    repo.get_action = AsyncMock(
        return_value=RepositoryResult(
            data={
                "action_id": action_id,
                "suggestion_id": suggestion_id,
                "user_id": user_id,
                "status": "processing",
            }
        )
    )
    repo.get_runtime_resume_context_for_user_step = AsyncMock(
        return_value=RepositoryResult(error="No data found")
    )
    repo.get_runtime_checkpoint_for_approval_resume = AsyncMock(
        return_value=RepositoryResult(error="No data found")
    )
    repo.update_action_status_if_processing = AsyncMock()
    repo.save_action = AsyncMock(return_value=RepositoryResult(data={}))
    return repo


def build_action_use_case(repo: MagicMock) -> ActionUseCaseService:
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        side_effect=fake_load_config,
    ):
        agent = ActionAgent(
            config={"llm_client": MockLLMClient(), "llm": {}}, repository=repo
        )
    return ActionUseCaseService(ActionUseCaseDeps(agent=agent))


def build_mock_action_use_case(
    repo: MockActionAgentRepository,
    *,
    llm_client: MockLLMClient | None = None,
) -> ActionUseCaseService:
    with patch(
        "pantaray_agents.agents.core.base.prompt_loader.load_config",
        side_effect=fake_load_config,
    ):
        agent = ActionAgent(
            config={"llm_client": llm_client or MockLLMClient(), "llm": {}},
            repository=repo,
        )
    return ActionUseCaseService(ActionUseCaseDeps(agent=agent))


def request(
    *,
    action_id: str,
    suggestion_id: str,
    user_id: str,
    language: Literal["en", "ja"] | None = None,
) -> ActionAgentRequest:
    return build_action_request(
        action_id=action_id,
        suggestion_id=suggestion_id,
        user_id=user_id,
        language=language,
    )
