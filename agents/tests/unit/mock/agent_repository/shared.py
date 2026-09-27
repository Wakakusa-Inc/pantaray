from datetime import UTC, datetime, timedelta

import pytest

from pantaray_agents.mock.mock_agent_repository import (
    MockActionAgentRepository,
    MockInsightAgentRepository,
    MockSuggestionAgentRepository,
)
from pantaray_agents.mock.mock_repository import MockRepository
from pantaray_agents.schema.agent.action import StepType
from pantaray_agents.schema.agent.base import StatusType
from pantaray_agents.schema.agent.suggestion import SuggestionAgentResponse
from pantaray_agents.utils.memory_source_policy import EMPTY_TEXT_SHA256_HEX

__all__ = [
    "EMPTY_TEXT_SHA256_HEX",
    "MockActionAgentRepository",
    "MockInsightAgentRepository",
    "MockSuggestionAgentRepository",
    "StatusType",
    "StepType",
    "SuggestionAgentResponse",
    "UTC",
    "datetime",
    "timedelta",
    "clear_mock_data",
]


@pytest.fixture(autouse=True)
def clear_mock_data():
    """各テストの前にモックデータをクリアするフィクスチャ"""
    MockRepository.clear_data()
    yield
    MockRepository.clear_data()
