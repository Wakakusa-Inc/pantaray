from __future__ import annotations

from .reads import LocalSuggestionStateRepositoryReadMixin
from .shared import LocalSuggestionStateRepositoryBase
from .writes import LocalSuggestionStateRepositoryWriteMixin


class LocalSuggestionStateRepository(
    LocalSuggestionStateRepositoryWriteMixin,
    LocalSuggestionStateRepositoryReadMixin,
    LocalSuggestionStateRepositoryBase,
):
    """Local runtime の suggestion/action current state と projection を扱う repository。"""
