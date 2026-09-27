from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from pantaray_agents.repositories.user_settings_port import LanguageCode
from pantaray_agents.schema.repositories.repository import DBRow, RepositoryResult

SQLITE_TIMESTAMP_NOW = "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"


@dataclass(frozen=True)
class LocalUserSettingsRepository:
    db_path: str
    busy_timeout_ms: int

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        connection.execute(f"PRAGMA busy_timeout = {self.busy_timeout_ms}")
        return connection

    async def get_ui_language(self, user_id: str) -> RepositoryResult[str | None]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT ui_language
                FROM users
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return RepositoryResult(data=None)
        value = row["ui_language"]
        if isinstance(value, str) and value in {"en", "ja"}:
            return RepositoryResult(data=value)
        return RepositoryResult(data=None)

    async def upsert_ui_language(
        self,
        user_id: str,
        ui_language: LanguageCode,
    ) -> RepositoryResult[DBRow]:
        with self._connect() as connection:
            with connection:
                connection.execute(
                    f"""
                    INSERT INTO users(
                        user_id,
                        ui_language,
                        created_at,
                        updated_at
                    ) VALUES (
                        ?,
                        ?,
                        {SQLITE_TIMESTAMP_NOW},
                        {SQLITE_TIMESTAMP_NOW}
                    )
                    ON CONFLICT(user_id) DO UPDATE SET
                        ui_language = excluded.ui_language,
                        updated_at = excluded.updated_at
                    """,
                    (user_id, ui_language),
                )
            row = connection.execute(
                """
                SELECT user_id, ui_language
                FROM users
                WHERE user_id = ?
                LIMIT 1
                """,
                (user_id,),
            ).fetchone()
        if row is None:
            return RepositoryResult(
                error="failed to persist ui_language into local users table"
            )
        return RepositoryResult(
            data={
                "user_id": str(row["user_id"]),
                "ui_language": str(row["ui_language"]),
            }
        )
