from __future__ import annotations

from typing import Literal, Protocol

from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult

type LanguageCode = Literal["en", "ja"]


class UserSettingsRepositoryPort(Protocol):
    async def get_ui_language(self, user_id: str) -> RepositoryResult[str | None]: ...

    async def upsert_ui_language(
        self,
        user_id: str,
        ui_language: LanguageCode,
    ) -> RepositoryResult[DBRow]: ...
