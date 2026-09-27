"""ActionAgent formatting facade."""

from __future__ import annotations

from collections.abc import Mapping

from pantaray_agents.agents.action_agent.tools import ToolDefinition

from .formatter_parts import (
    GoalFormattingMixin,
    HistoryDisplayEntry,
    HistoryFormattingMixin,
    PromptFormattingMixin,
    format_tool_summary_list,
    normalize_prompt_text,
)


class ActionAgentFormatter(
    PromptFormattingMixin,
    HistoryFormattingMixin,
    GoalFormattingMixin,
):
    """ActionAgent が扱う各種データの整形責務を束ねる facade。"""

    def __init__(self, tool_registry: Mapping[str, ToolDefinition]) -> None:
        self._tool_registry = tool_registry


__all__ = [
    "ActionAgentFormatter",
    "HistoryDisplayEntry",
    "format_tool_summary_list",
    "normalize_prompt_text",
]
