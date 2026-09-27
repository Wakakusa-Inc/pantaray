from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.runtime import session_store
from pantaray_agents.local_runtime.runtime.connection_store import (
    ApiKeyConnection,
    ApiKeyProvider,
    ChatGptConnection,
    ChatGptCredential,
    LlmConnection,
    WebSearchCredential,
    set_llm_connection,
)
from pantaray_agents.local_runtime.runtime.identity import (
    current_owner_id,
    register_logged_out_owner,
    reset_logged_out_owner,
)
from pantaray_agents.local_runtime.runtime.route_identity import (
    EffectiveRouteIdentity,
    RouteInputs,
    connection_identity,
    effective_route_identity,
    read_route_inputs,
    web_search_identity,
)
from pantaray_agents.local_runtime.runtime.session_store import (
    AUTH_CONTEXT_EXPIRED_STATE,
    CloudSessionIdentity,
    forget_cloud_session,
    import_desktop_session,
    mark_configured,
    peek_cloud_session_identity_without_settling,
    read_auth_context_state,
    restore_expired_cloud_identity,
)
from pantaray_agents.local_runtime.storage.migrations.specs import (
    load_default_migrations,
)

from .migrated_db import prepare_test_database

GUEST_OWNER = "local-guest-owner"
ACCOUNT_OWNER = "account-1"
BUSY_TIMEOUT_MS = 1_000
CHATGPT_ACCESS_TOKEN = "chatgpt-access-token"
OPENAI_API_KEY = "sk-openai-key"
TAVILY_API_KEY = "tvly-search-key"


def _api_key(
    *,
    provider: ApiKeyProvider = "openai",
    model: str = "gpt-5",
    api_key: str = OPENAI_API_KEY,
) -> ApiKeyConnection:
    return ApiKeyConnection(provider=provider, model=model, api_key=api_key)


def _chatgpt(
    *,
    model: str = "gpt-5-codex",
    account_id: str = "chatgpt-account",
    access_token: str = CHATGPT_ACCESS_TOKEN,
    expires_at: str = "2026-09-18T00:00:00Z",
) -> ChatGptConnection:
    return ChatGptConnection(
        model=model,
        credential=ChatGptCredential(
            access_token=access_token,
            expires_at=expires_at,
            account_id=account_id,
        ),
    )


def _signed_in(*, session_version: str = "7") -> CloudSessionIdentity:
    return CloudSessionIdentity(
        state="present",
        user_id=ACCOUNT_OWNER,
        session_version=session_version,
    )


def _inputs(
    *,
    configured: bool = True,
    cloud: CloudSessionIdentity | None = None,
    llm: LlmConnection | None = None,
    web_search: WebSearchCredential | None = None,
) -> RouteInputs:
    return RouteInputs(
        configured=configured,
        logged_out_owner_id=GUEST_OWNER,
        cloud=cloud,
        llm=None if llm is None else connection_identity(llm),
        web_search=None if web_search is None else web_search_identity(web_search),
    )


def _identity(inputs: RouteInputs) -> EffectiveRouteIdentity:
    return effective_route_identity(inputs)


@pytest.mark.parametrize(
    ("before", "after", "unchanged"),
    [
        pytest.param(
            _inputs(
                llm=_chatgpt(access_token="old", expires_at="2026-09-18T00:00:00Z")
            ),
            _inputs(
                llm=_chatgpt(access_token="new", expires_at="2026-12-01T00:00:00Z")
            ),
            True,
            id="chatgpt-token-refresh-keeps-the-account",
        ),
        pytest.param(
            _inputs(llm=_chatgpt(account_id="chatgpt-account")),
            _inputs(llm=_chatgpt(account_id="other-chatgpt-account")),
            False,
            id="chatgpt-account-switch",
        ),
        pytest.param(
            _inputs(llm=_api_key(api_key="sk-old")),
            _inputs(llm=_api_key(api_key="sk-new")),
            False,
            id="api-key-replacement",
        ),
        pytest.param(
            _inputs(llm=_api_key(model="gpt-5")),
            _inputs(llm=_api_key(model="gpt-5-mini")),
            True,
            id="model-change",
        ),
        pytest.param(
            _inputs(llm=_chatgpt(model="gpt-6-luna")),
            _inputs(llm=_chatgpt(model="gpt-5.5")),
            True,
            id="chatgpt-model-change",
        ),
        pytest.param(
            _inputs(llm=_api_key(provider="openai")),
            _inputs(llm=_api_key(provider="anthropic")),
            False,
            id="provider-change",
        ),
        pytest.param(
            _inputs(cloud=_signed_in(session_version="7")),
            _inputs(cloud=_signed_in(session_version="8")),
            False,
            id="new-sign-in-of-the-same-account",
        ),
        pytest.param(
            _inputs(cloud=_signed_in()),
            _inputs(cloud=CloudSessionIdentity("expired", ACCOUNT_OWNER, "7")),
            False,
            id="session-expiry",
        ),
        pytest.param(
            _inputs(cloud=_signed_in()),
            _inputs(
                cloud=_signed_in(),
                llm=_api_key(),
                web_search=WebSearchCredential(api_key=TAVILY_API_KEY),
            ),
            True,
            id="direct-settings-stored-while-signed-in",
        ),
        pytest.param(
            _inputs(cloud=_signed_in(), llm=_api_key(api_key="sk-old")),
            _inputs(cloud=_signed_in(), llm=_api_key(api_key="sk-new")),
            True,
            id="direct-settings-changed-while-signed-in",
        ),
        pytest.param(
            _inputs(
                cloud=_signed_in(),
                llm=_api_key(),
                web_search=WebSearchCredential(api_key=TAVILY_API_KEY),
            ),
            _inputs(cloud=_signed_in()),
            True,
            id="direct-settings-cleared-while-signed-in",
        ),
        pytest.param(
            _inputs(web_search=WebSearchCredential(api_key="tvly-old")),
            _inputs(web_search=WebSearchCredential(api_key="tvly-new")),
            False,
            id="search-key-replacement-while-signed-out",
        ),
        pytest.param(
            _inputs(llm=_api_key()),
            _inputs(),
            False,
            id="direct-connection-cleared-while-signed-out",
        ),
        pytest.param(
            _inputs(configured=False),
            _inputs(configured=False, cloud=_signed_in()),
            False,
            id="owner-switch-before-configure-is-applied",
        ),
        pytest.param(
            _inputs(cloud=_signed_in(), llm=_api_key()),
            _inputs(llm=_api_key()),
            False,
            id="sign-out-onto-a-stored-direct-connection",
        ),
    ],
)
def test_the_barrier_follows_one_identity_comparison(
    before: RouteInputs, after: RouteInputs, unchanged: bool
) -> None:
    assert (_identity(before) == _identity(after)) is unchanged


def test_a_search_key_replacement_leaves_the_llm_identity_alone() -> None:
    before = _identity(
        _inputs(llm=_api_key(), web_search=WebSearchCredential(api_key="tvly-old"))
    )
    after = _identity(
        _inputs(llm=_api_key(), web_search=WebSearchCredential(api_key="tvly-new"))
    )

    assert before.llm == after.llm
    assert before.web_search != after.web_search


def test_an_identity_never_carries_a_secret() -> None:
    inputs = _inputs(
        llm=_chatgpt(access_token=CHATGPT_ACCESS_TOKEN),
        web_search=WebSearchCredential(api_key=TAVILY_API_KEY),
    )
    rendered = (
        f"{inputs!r} {_identity(inputs)!r} {_identity(_inputs(llm=_api_key()))!r}"
    )

    assert CHATGPT_ACCESS_TOKEN not in rendered
    assert TAVILY_API_KEY not in rendered
    assert OPENAI_API_KEY not in rendered


@pytest.fixture()
def runtime_db(tmp_path: Path) -> Iterator[Path]:
    """A migrated store plus the logged-out owner every runtime read needs."""
    db_path = tmp_path / "runtime.db"
    prepare_test_database(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        migrations=load_default_migrations(),
    )
    register_logged_out_owner(GUEST_OWNER)
    try:
        yield db_path
    finally:
        reset_logged_out_owner()


def _sign_in(db_path: Path, *, access_token: str, session_version: str) -> None:
    import_desktop_session(
        db_path=db_path,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=ACCOUNT_OWNER,
        desktop_access_token=access_token,
        expires_at=(datetime.now(UTC) + timedelta(hours=1))
        .isoformat()
        .replace("+00:00", "Z"),
        session_version=session_version,
    )


def test_read_route_inputs_follows_the_live_cloud_session(runtime_db: Path) -> None:
    mark_configured()
    set_llm_connection(_api_key())
    signed_out = _identity(read_route_inputs())
    assert signed_out.owner_id == current_owner_id()
    assert signed_out.llm == connection_identity(_api_key())

    _sign_in(runtime_db, access_token="pantaray-token", session_version="7")
    signed_in = _identity(read_route_inputs())
    assert signed_in.owner_id == current_owner_id() == ACCOUNT_OWNER
    assert signed_in.llm == _signed_in()
    assert signed_in != signed_out

    # A refreshed Pantaray access token is the same identity: nothing stops.
    _sign_in(runtime_db, access_token="refreshed-pantaray-token", session_version="7")
    assert _identity(read_route_inputs()) == signed_in

    restore_expired_cloud_identity(
        db_path=runtime_db,
        busy_timeout_ms=BUSY_TIMEOUT_MS,
        user_id=ACCOUNT_OWNER,
        session_version="7",
    )
    expired = _identity(read_route_inputs())
    assert expired.owner_id == current_owner_id() == ACCOUNT_OWNER
    assert expired != signed_in

    forget_cloud_session()
    assert _identity(read_route_inputs()) == signed_out


def test_a_lapsed_session_stays_present_until_something_settles_it(
    runtime_db: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Settling an expiry is itself a change the barrier has to stop for.

    Every other cloud-session read settles a lapsed ``present`` session as a
    side effect. If the snapshot did that, the ``expired`` transition would
    already have happened by the time the two sides are compared, and nothing
    would stop the run that is still using the cloud route.
    """
    mark_configured()
    _sign_in(runtime_db, access_token="pantaray-token", session_version="7")
    monkeypatch.setattr(
        session_store, "_now_utc", lambda: datetime.now(UTC) + timedelta(hours=2)
    )

    lapsed = _identity(read_route_inputs())
    assert lapsed.llm == _signed_in()
    assert peek_cloud_session_identity_without_settling() == _signed_in()

    assert read_auth_context_state() == AUTH_CONTEXT_EXPIRED_STATE
    assert _identity(read_route_inputs()) != lapsed
