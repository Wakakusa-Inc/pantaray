from __future__ import annotations

from .events import LocalSuggestionStateRepositoryEventMixin
from .shared import LocalSuggestionStateRepositoryBase
from .terminal import LocalSuggestionStateRepositoryTerminalMixin


class LocalSuggestionStateRepositoryWriteMixin(
    LocalSuggestionStateRepositoryTerminalMixin,
    LocalSuggestionStateRepositoryEventMixin,
    LocalSuggestionStateRepositoryBase,
):
    """Local runtime の write-side transaction 群。"""
