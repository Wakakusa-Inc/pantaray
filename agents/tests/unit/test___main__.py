from __future__ import annotations

import argparse
import os

from pantaray_agents import __main__
from pantaray_agents.local_runtime.runtime.runtime_env import (
    LOCAL_BACKEND_BOUND_HOST_ENV,
    LOCAL_BACKEND_BOUND_PORT_ENV,
)


def test_apply_cli_env_overrides_sets_mock_and_cors_env(monkeypatch) -> None:
    monkeypatch.delenv("USE_MOCKS", raising=False)
    monkeypatch.delenv("ALLOWED_ORIGINS", raising=False)
    monkeypatch.delenv("ALLOWED_HOSTS", raising=False)
    args = argparse.Namespace(
        mock=True,
        port=9000,
        host="127.0.0.1",
        origins="http://localhost:3000",
        hosts="localhost",
        reload=False,
    )

    __main__._apply_cli_env_overrides(args)

    assert os.environ["USE_MOCKS"] == "true"
    assert os.environ["ALLOWED_ORIGINS"] == "http://localhost:3000"
    assert os.environ["ALLOWED_HOSTS"] == "localhost"


def test_apply_cli_env_overrides_mock_flag_overrides_existing_env(monkeypatch) -> None:
    monkeypatch.setenv("USE_MOCKS", "false")
    args = argparse.Namespace(
        mock=True,
        port=None,
        host=None,
        origins=None,
        hosts=None,
        reload=False,
    )

    __main__._apply_cli_env_overrides(args)

    assert os.environ["USE_MOCKS"] == "true"


def test_resolve_uvicorn_runtime_uses_cli_values() -> None:
    args = argparse.Namespace(
        mock=False,
        port=9001,
        host="127.0.0.1",
        origins=None,
        hosts=None,
        reload=True,
    )

    assert __main__._resolve_uvicorn_port(args) == 9001
    assert __main__._resolve_uvicorn_host(args) == "127.0.0.1"


def test_resolve_uvicorn_runtime_uses_defaults_without_cli_values() -> None:
    args = argparse.Namespace(
        mock=False,
        port=None,
        host=None,
        origins=None,
        hosts=None,
        reload=False,
    )

    assert __main__._resolve_uvicorn_port(args) == __main__.DEFAULT_UVICORN_PORT
    assert __main__._resolve_uvicorn_host(args) == __main__.DEFAULT_UVICORN_HOST


def test_bind_uvicorn_socket_allows_dynamic_loopback_port(monkeypatch) -> None:
    monkeypatch.delenv(LOCAL_BACKEND_BOUND_HOST_ENV, raising=False)
    monkeypatch.delenv(LOCAL_BACKEND_BOUND_PORT_ENV, raising=False)

    sock = __main__._bind_uvicorn_socket("127.0.0.1", 0)
    try:
        bound_port = __main__._publish_bound_loopback("127.0.0.1", sock)

        assert bound_port > 0
        assert os.environ[LOCAL_BACKEND_BOUND_HOST_ENV] == "127.0.0.1"
        assert os.environ[LOCAL_BACKEND_BOUND_PORT_ENV] == str(bound_port)
    finally:
        sock.close()
