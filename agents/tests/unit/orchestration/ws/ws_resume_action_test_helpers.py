from __future__ import annotations

from collections.abc import Iterator

import pytest
from starlette.testclient import TestClient

from pantaray_agents.local_runtime.runtime.identity import (
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.local_api_auth import (
    clear_local_api_token,
    issue_local_api_token,
    read_local_api_token,
)

LOCAL_WS_OWNER_ID = "user-1"


def local_ws_app_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A local app whose runtime start only mints the local API token."""
    monkeypatch.setenv("NODE_ENV", "test")
    monkeypatch.setenv("USE_MOCKS", "true")
    monkeypatch.setattr("pantaray_agents.dependencies.is_mock_mode", lambda: True)

    from pantaray_agents.app import local_app

    monkeypatch.setitem(local_app.settings, "use_mocks", True)
    monkeypatch.setattr(
        local_app, "start_local_runtime_if_enabled", issue_local_api_token
    )
    monkeypatch.setattr(
        local_app, "stop_local_runtime_if_enabled", clear_local_api_token
    )
    register_logged_out_owner(LOCAL_WS_OWNER_ID)
    try:
        with TestClient(local_app.create_local_app()) as client:
            yield client
    finally:
        reset_logged_out_owner()
        clear_local_api_token()


def local_ws_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {read_local_api_token()}"}


def register_suggestion_resume_session(
    *,
    session_id: str,
    process_id: str = "p1",
    user_id: str = "user-1",
) -> None:
    from pantaray_agents.orchestration import router as orch_router

    orch_router.SESSION_STORE.create_session(session_id, user_id=user_id)
    orch_router.SESSION_STORE.ensure_process(session_id, process_id)
    orch_router.SESSION_STORE.set_process_metadata(
        session_id,
        process_id,
        suggestion_id="s1",
        action_id=None,
        command_id=None,
        kind="suggestion",
    )


def patch_action_relay_authority(monkeypatch, *, row=None, error=None) -> None:
    from pantaray_agents.local_runtime.storage.migrations import MigrationError
    from pantaray_agents.orchestration.ws.action_relay_authority import (
        ActionRelayAuthority,
        ActionRelayAuthorityError,
    )

    def _load_authority(*, user_id: str, action_id: str, process_id: str):
        if error:
            raise MigrationError(str(error))
        if not isinstance(row, dict):
            raise ActionRelayAuthorityError("missing authority")
        if (
            row.get("action_id") != action_id
            or row.get("action_process_id") != process_id
        ):
            raise ActionRelayAuthorityError("identity mismatch")
        status = row.get("action_status")
        suggestion_id = row.get("suggestion_id", "s1")
        return ActionRelayAuthority(
            user_id=user_id,
            action_id=action_id,
            process_id=process_id,
            root_process_id=str(row["root_process_id"]),
            command_id=str(row.get("action_command_id") or "cmd-1"),
            suggestion_id=None if suggestion_id is None else str(suggestion_id),
            action_status=status,
            terminal_cursor=row.get(
                "terminal_cursor",
                8 if status in {"success", "error", "canceled"} else None,
            ),
        )

    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.session_resume.load_action_relay_authority",
        _load_authority,
    )


def patch_action_resume_cursor(monkeypatch, *, cursor: int | None = 7) -> None:
    monkeypatch.setattr(
        "pantaray_agents.orchestration.ws.handler.WSOrchestrationHandler._resolve_action_start_after_cursor",
        lambda *_args, **_kwargs: cursor,
        raising=False,
    )
