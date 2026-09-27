"""`python -m pantaray_agents` launches the local backend entrypoint for development."""

from __future__ import annotations

import argparse
import logging
import os
import socket

import uvicorn

from pantaray_agents.local_runtime.runtime.runtime_env import (
    LOCAL_BACKEND_BOUND_HOST_ENV,
    LOCAL_BACKEND_BOUND_PORT_ENV,
)

DEFAULT_UVICORN_HOST = "0.0.0.0"
DEFAULT_UVICORN_PORT = 8000


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--mock", action="store_true")
    parser.add_argument("--port", type=int)
    parser.add_argument("--host", type=str)
    parser.add_argument("--origins", type=str)
    parser.add_argument("--hosts", type=str)
    parser.add_argument("--reload", action="store_true")
    return parser


def _parse_args() -> argparse.Namespace:
    return _build_parser().parse_known_args()[0]


def _apply_cli_env_overrides(args: argparse.Namespace) -> None:
    if args.mock:
        os.environ["USE_MOCKS"] = "true"
    if args.origins:
        os.environ["ALLOWED_ORIGINS"] = str(args.origins)
    if args.hosts:
        os.environ["ALLOWED_HOSTS"] = str(args.hosts)


logger = logging.getLogger(__name__)


def _resolve_uvicorn_host(args: argparse.Namespace) -> str:
    return (
        args.host
        if isinstance(args.host, str) and args.host.strip()
        else DEFAULT_UVICORN_HOST
    )


def _resolve_uvicorn_port(args: argparse.Namespace) -> int:
    return args.port if isinstance(args.port, int) else DEFAULT_UVICORN_PORT


def _bind_uvicorn_socket(host: str, port: int) -> socket.socket:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.bind((host, port))
        sock.listen(socket.SOMAXCONN)
        return sock
    except Exception:
        sock.close()
        raise


def _publish_bound_loopback(socket_host: str, sock: socket.socket) -> int:
    bound = sock.getsockname()
    bound_port = int(bound[1])
    os.environ[LOCAL_BACKEND_BOUND_HOST_ENV] = socket_host
    os.environ[LOCAL_BACKEND_BOUND_PORT_ENV] = str(bound_port)
    return bound_port


def main() -> None:
    """ローカル開発向けに Uvicorn を起動する。"""
    args = _parse_args()
    _apply_cli_env_overrides(args)

    from pantaray_agents.config_local_runtime import LOG_LEVEL
    from pantaray_agents.entrypoints.main_local import app

    port = _resolve_uvicorn_port(args)
    host = _resolve_uvicorn_host(args)
    reload = bool(args.reload)
    log_level_uvicorn = str(LOG_LEVEL).lower()
    if reload:
        if port <= 0:
            raise ValueError("--reload requires an explicit positive --port")
        os.environ[LOCAL_BACKEND_BOUND_HOST_ENV] = host
        os.environ[LOCAL_BACKEND_BOUND_PORT_ENV] = str(port)
        logger.info(
            "Starting Uvicorn server on %s:%s with log level %s",
            host,
            port,
            log_level_uvicorn,
        )
        uvicorn.run(
            app,
            host=host,
            port=port,
            reload=True,
            log_level=log_level_uvicorn,
        )
        return

    sock = _bind_uvicorn_socket(host, port)
    bound_port = _publish_bound_loopback(host, sock)

    logger.info(
        "Starting Uvicorn server on %s:%s with log level %s",
        host,
        bound_port,
        log_level_uvicorn,
    )
    config = uvicorn.Config(
        app,
        host=host,
        port=bound_port,
        log_level=log_level_uvicorn,
    )
    server = uvicorn.Server(config)
    server.run(sockets=[sock])


if __name__ == "__main__":
    main()
