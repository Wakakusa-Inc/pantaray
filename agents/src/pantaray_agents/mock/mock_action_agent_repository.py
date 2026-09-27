"""MockActionAgentRepository の公開ファサード。"""

from __future__ import annotations

from .action_agent_repository import (
    MockActionAgentMemoryMixin,
    MockActionAgentMutationMixin,
    MockActionAgentQueryMixin,
)
from .mock_repository import MockRepository


class MockActionAgentRepository(
    MockActionAgentMutationMixin,
    MockActionAgentQueryMixin,
    MockActionAgentMemoryMixin,
    MockRepository,
):
    """ActionAgentRepository のモック実装。"""

    def __init__(self) -> None:
        super().__init__()
        self._next_save_action_error: str | None = None
