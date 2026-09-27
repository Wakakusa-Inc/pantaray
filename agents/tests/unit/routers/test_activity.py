from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    from pantaray_agents.entrypoints.main_local import app
    from pantaray_agents.routers import activity as activity_router

    monkeypatch.setattr(activity_router, "settings", {"use_mocks": False})

    async def fake_user_id() -> str:
        return "test_user"

    app.dependency_overrides[activity_router.get_current_user_id_from_token] = (
        fake_user_id
    )
    test_client = TestClient(app)
    try:
        yield test_client, activity_router
    finally:
        app.dependency_overrides.clear()


def test_generate_activity_summary_enqueues_job(client):
    test_client, activity_router = client
    captured: dict[str, object] = {}

    def _fake_enqueue(**kwargs: object) -> dict[str, str]:
        captured["payload"] = kwargs
        return {
            "job_id": "job-1",
            "process_id": "process-1",
            "summary_id": "summary-1",
        }

    with patch.object(
        activity_router, "enqueue_activity_summary_job", new=_fake_enqueue
    ):
        response = test_client.post(
            "/v1/agents/users/test_user/activities/summaries/summary-1",
            json={
                "summary_type": "24h",
                "period_start": "2026-03-21T00:00:00Z",
                "period_end": "2026-03-22T00:00:00Z",
            },
            headers={"X-Request-ID": "req-activity-summary-1"},
        )

    assert response.status_code == 202
    body = response.json()
    assert body["summary_id"] == "summary-1"
    assert body["status"] == "processing"
    assert "prompt_text" not in body
    payload = captured["payload"]
    assert payload["user_id"] == "test_user"
    assert payload["summary_id"] == "summary-1"
