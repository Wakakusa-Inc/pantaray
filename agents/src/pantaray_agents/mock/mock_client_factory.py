"""モッククライアントファクトリ"""

from typing import Any

from ..mock.mock_agent_repository import (
    MockActionAgentRepository,
    MockInsightAgentRepository,
    MockSuggestionAgentRepository,
)
from ..mock.mock_llm_client import MockLLMClient


def create_mock_client(config: dict[str, Any] | None = None) -> Any:
    """モックLLMクライアントを作成する

    Args:
        config (Optional[Dict[str, Any]], optional): 設定. デフォルトはNone.

    Returns:
        Any: モックLLMクライアント
    """
    return MockLLMClient(config)


def create_mock_suggestion_repository() -> MockSuggestionAgentRepository:
    """モックサジェスチョンリポジトリを作成する

    Returns:
        MockSuggestionAgentRepository: モックサジェスチョンリポジトリ
    """
    return MockSuggestionAgentRepository()


def create_mock_action_repository() -> MockActionAgentRepository:
    """モックアクションリポジトリを作成する

    Returns:
        MockActionAgentRepository: モックアクションリポジトリ
    """
    return MockActionAgentRepository()


def create_mock_insight_repository() -> MockInsightAgentRepository:
    """モックインサイトリポジトリを作成する

    Returns:
        MockInsightAgentRepository: モックインサイトリポジトリ
    """
    return MockInsightAgentRepository()
