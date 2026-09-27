from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations,
)
from pantaray_agents.local_runtime.user_settings_repository import (
    LocalUserSettingsRepository,
)

from .migrated_db import prepare_test_database

BUSY_TIMEOUT_MS = 1_000


def _bootstrap_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    with sqlite3.connect(db_path) as connection:
        with connection:
            connection.execute(
                """
                INSERT INTO users(
                    user_id,
                    ui_language,
                    created_at,
                    updated_at
                ) VALUES ('user-1', 'ja', '2026-03-24T00:00:00Z', '2026-03-24T00:00:00Z')
                """
            )
    return db_path


@pytest.mark.asyncio
async def test_local_user_settings_repository_reads_and_updates_users_table(
    tmp_path: Path,
) -> None:
    db_path = _bootstrap_db(tmp_path)
    repo = LocalUserSettingsRepository(
        db_path=str(db_path),
        busy_timeout_ms=BUSY_TIMEOUT_MS,
    )

    initial = await repo.get_ui_language("user-1")
    assert initial.error is None
    assert initial.data == "ja"

    updated = await repo.upsert_ui_language("user-1", "en")
    assert updated.error is None
    assert updated.data == {"user_id": "user-1", "ui_language": "en"}

    reread = await repo.get_ui_language("user-1")
    assert reread.error is None
    assert reread.data == "en"
