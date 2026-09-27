from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from pantaray_agents.auth_http import get_current_user_id_from_token
from pantaray_agents.local_runtime.storage.migrations import (
    apply_migrations,
    load_default_migrations,
)
from pantaray_agents.local_runtime.storage.sqlite_vector import (
    load_sqlite_vector_extension,
)
from pantaray_agents.local_runtime.storage.users import ensure_user_row
from pantaray_agents.local_runtime.tooling.repository.command_network_settings import (
    load_command_network_enabled,
)
from pantaray_agents.routers import workspace_settings

SETTINGS_URL = "/v1/agents/users/user-1/workspace-settings/command-network"


@pytest.fixture
def settings_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path, busy_timeout_ms=1_000, migrations=load_default_migrations()
    )
    monkeypatch.setattr(
        workspace_settings, "read_local_runtime_db_config", lambda: (db_path, 1_000)
    )
    return db_path


def _client(user_id: str = "user-1") -> TestClient:
    app = FastAPI()
    app.include_router(workspace_settings.router)
    app.dependency_overrides[get_current_user_id_from_token] = lambda: user_id
    return TestClient(app)


def test_network_setting_defaults_on_and_persists_off_for_only_its_user(
    settings_db: Path,
) -> None:
    with _client() as client:
        assert client.get(SETTINGS_URL).json() == {"command_network_enabled": True}
        for _ in range(2):
            response = client.put(SETTINGS_URL, json={"command_network_enabled": False})
            assert response.status_code == 200
            assert response.json() == {"command_network_enabled": False}

    # A fresh API instance and DB connection must observe the persisted choice.
    with _client() as restarted, _client("user-2") as other_user:
        assert restarted.get(SETTINGS_URL).json() == {"command_network_enabled": False}
        assert other_user.get(SETTINGS_URL.replace("user-1", "user-2")).json() == {
            "command_network_enabled": True
        }
        restored = restarted.put(SETTINGS_URL, json={"command_network_enabled": True})
        assert restored.status_code == 200
        assert restarted.get(SETTINGS_URL).json() == {"command_network_enabled": True}
    with sqlite3.connect(settings_db) as connection:
        assert connection.execute(
            "SELECT count(*) FROM command_network_preferences"
        ).fetchone() == (1,)


@pytest.mark.parametrize("method", ["get", "put"])
def test_network_settings_reject_another_authenticated_user(
    settings_db: Path, method: str
) -> None:
    with _client("user-2") as client:
        response = client.request(
            method, SETTINGS_URL, json={"command_network_enabled": False}
        )
    assert response.status_code == 403
    assert load_command_network_enabled(
        db_path=settings_db, busy_timeout_ms=1_000, user_id="user-1"
    )


@pytest.mark.parametrize(
    "body",
    [
        {},
        {"command_network_enabled": "false"},
        {"command_network_enabled": 0},
        {"command_network_enabled": None},
        {"command_network_enabled": False, "user_id": "user-2"},
    ],
)
def test_network_settings_validate_the_update_at_the_http_boundary(
    settings_db: Path, body: dict[str, object]
) -> None:
    with _client() as client:
        assert client.put(SETTINGS_URL, json=body).status_code == 422
        assert client.get(SETTINGS_URL).json() == {"command_network_enabled": True}


@pytest.mark.parametrize("method", ["get", "put"])
def test_unavailable_setting_storage_is_an_error_not_on_or_save_success(
    settings_db: Path, method: str
) -> None:
    with sqlite3.connect(settings_db) as connection:
        connection.execute("DROP TABLE command_network_preferences")
    with _client() as client:
        response = client.request(
            method, SETTINGS_URL, json={"command_network_enabled": False}
        )
    assert response.status_code == 500
    assert "command_network_enabled" not in response.json()
    with pytest.raises(sqlite3.OperationalError):
        load_command_network_enabled(
            db_path=settings_db, busy_timeout_ms=1_000, user_id="user-1"
        )


def test_setting_is_removed_with_its_user(settings_db: Path) -> None:
    with _client() as client:
        assert (
            client.put(
                SETTINGS_URL, json={"command_network_enabled": False}
            ).status_code
            == 200
        )
    with sqlite3.connect(settings_db) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        load_sqlite_vector_extension(connection)
        connection.execute("DELETE FROM users WHERE user_id = 'user-1'")
        assert connection.execute(
            "SELECT count(*) FROM command_network_preferences"
        ).fetchone() == (0,)


def test_migration_preserves_existing_user_and_rejects_non_boolean_storage(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "upgrade.db"
    migrations = load_default_migrations()
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=tuple(item for item in migrations if item.version < 110),
    )
    with sqlite3.connect(db_path) as connection:
        ensure_user_row(connection, user_id="existing-user")
        connection.execute("UPDATE users SET ui_language = 'en'")
    apply_migrations(db_path=db_path, busy_timeout_ms=1_000, migrations=migrations)
    assert load_command_network_enabled(
        db_path=db_path, busy_timeout_ms=1_000, user_id="existing-user"
    )
    with sqlite3.connect(db_path) as connection:
        assert connection.execute("SELECT ui_language FROM users").fetchone() == ("en",)
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO command_network_preferences VALUES (?, ?, ?)",
                ("existing-user", "not-a-boolean", "2026-09-11T00:00:00Z"),
            )
