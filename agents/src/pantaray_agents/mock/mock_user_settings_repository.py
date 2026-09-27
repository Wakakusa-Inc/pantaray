"""ユーザー設定（system_users 相当）のモックリポジトリ。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult

LanguageCode = Literal["en", "ja"]


@dataclass(slots=True)
class MockUserSettingsRepository:
    """system_users.ui_language の読み書きだけを提供する軽量モック。"""

    _ui_language_by_user: dict[str, LanguageCode] = field(default_factory=dict)

    async def get_ui_language(self, user_id: str) -> RepositoryResult[str | None]:
        value = self._ui_language_by_user.get(user_id)
        return RepositoryResult(data=value)

    async def upsert_ui_language(
        self, user_id: str, ui_language: LanguageCode
    ) -> RepositoryResult[DBRow]:
        self._ui_language_by_user[user_id] = ui_language
        return RepositoryResult(data={"user_id": user_id, "ui_language": ui_language})
