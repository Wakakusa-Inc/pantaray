"""Integration tests for FastAPI app wiring (minimal, current endpoints).

This suite intentionally avoids external Supabase/JWT dependencies by overriding
authentication-related dependencies.
"""

from __future__ import annotations

import importlib
from collections.abc import AsyncIterator

import httpx2
import pytest
import pytest_asyncio

from pantaray_agents.auth_http import get_current_user_id_from_token
from pantaray_agents.settings_loader import (
    LOCAL_RUNTIME_SETTINGS_MODULE,
    clear_active_settings_module,
    register_active_settings_module,
)


@pytest_asyncio.fixture(scope="function")
async def client(
    monkeypatch: pytest.MonkeyPatch,
) -> AsyncIterator[httpx2.AsyncClient]:
    monkeypatch.setenv("USE_MOCKS", "true")

    main_local = importlib.import_module("pantaray_agents.entrypoints.main_local")
    app = main_local.app

    # Ensure routers run in mock mode (avoid external Supabase network calls).
    register_active_settings_module(LOCAL_RUNTIME_SETTINGS_MODULE)

    async def fake_user_id() -> str:
        return "user_123"

    app.dependency_overrides[get_current_user_id_from_token] = fake_user_id

    transport = httpx2.ASGITransport(app=app)
    async with httpx2.AsyncClient(
        base_url="http://testserver", transport=transport
    ) as c:
        yield c

    app.dependency_overrides.clear()
    clear_active_settings_module()


@pytest.mark.asyncio
async def test_health_check(client: httpx2.AsyncClient):
    resp = await client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
