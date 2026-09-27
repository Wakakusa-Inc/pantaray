from __future__ import annotations

import os
from pathlib import Path

from pantaray_agents.local_runtime.storage.migrations import MigrationError

LOCAL_RUNTIME_CONTROL_SOCKET_DIRNAME = "local-backend"
LOCAL_RUNTIME_CONTROL_SOCKET_FILENAME = "control.sock"
LOCAL_DB_PATH_ENV = "LOCAL_DB_PATH"
LOCAL_DB_BUSY_TIMEOUT_MS_ENV = "LOCAL_DB_BUSY_TIMEOUT_MS"
LOCAL_ARTIFACT_ROOT_ENV = "LOCAL_ARTIFACT_ROOT"
HELPER_INSTANCE_ID_ENV = "PANTARAY_HELPER_INSTANCE_ID"
MAIN_PROCESS_PID_ENV = "PANTARAY_MAIN_PROCESS_PID"
LOCAL_BACKEND_BOUND_HOST_ENV = "PANTARAY_LOCAL_BACKEND_BOUND_HOST"
LOCAL_BACKEND_BOUND_PORT_ENV = "PANTARAY_LOCAL_BACKEND_BOUND_PORT"


def _read_required_env(name: str) -> str:
    value = os.getenv(name)
    if value is None or not value.strip():
        raise MigrationError(f"Missing required environment variable: {name}")
    return value


def read_local_runtime_db_config() -> tuple[Path, int]:
    db_path = Path(_read_required_env(LOCAL_DB_PATH_ENV))
    timeout_raw = _read_required_env(LOCAL_DB_BUSY_TIMEOUT_MS_ENV)
    try:
        timeout_ms = int(timeout_raw)
    except ValueError as exc:
        raise MigrationError(
            f"{LOCAL_DB_BUSY_TIMEOUT_MS_ENV} must be an integer: {timeout_raw!r}"
        ) from exc
    return db_path, timeout_ms


def read_local_runtime_artifact_root() -> Path:
    return Path(_read_required_env(LOCAL_ARTIFACT_ROOT_ENV))


def build_local_runtime_control_socket_path(user_data_dir: Path) -> Path:
    return (
        user_data_dir
        / LOCAL_RUNTIME_CONTROL_SOCKET_DIRNAME
        / LOCAL_RUNTIME_CONTROL_SOCKET_FILENAME
    )


def read_local_runtime_control_socket_path() -> Path:
    db_path, _ = read_local_runtime_db_config()
    return build_local_runtime_control_socket_path(db_path.parent)


def read_helper_instance_id() -> str:
    return _read_required_env(HELPER_INSTANCE_ID_ENV)


def read_local_backend_bound_host() -> str:
    return _read_required_env(LOCAL_BACKEND_BOUND_HOST_ENV)


def read_local_backend_bound_port() -> int:
    port_raw = _read_required_env(LOCAL_BACKEND_BOUND_PORT_ENV)
    try:
        port = int(port_raw)
    except ValueError as exc:
        raise MigrationError(
            f"{LOCAL_BACKEND_BOUND_PORT_ENV} must be an integer: {port_raw!r}"
        ) from exc
    if port <= 0:
        raise MigrationError(
            f"{LOCAL_BACKEND_BOUND_PORT_ENV} must be a positive integer"
        )
    return port


def read_main_process_pid() -> int:
    pid_raw = _read_required_env(MAIN_PROCESS_PID_ENV)
    try:
        pid = int(pid_raw)
    except ValueError as exc:
        raise MigrationError(
            f"{MAIN_PROCESS_PID_ENV} must be an integer: {pid_raw!r}"
        ) from exc
    if pid <= 0:
        raise MigrationError(f"{MAIN_PROCESS_PID_ENV} must be a positive integer")
    return pid


__all__ = [
    "HELPER_INSTANCE_ID_ENV",
    "LOCAL_BACKEND_BOUND_HOST_ENV",
    "LOCAL_BACKEND_BOUND_PORT_ENV",
    "LOCAL_ARTIFACT_ROOT_ENV",
    "LOCAL_DB_BUSY_TIMEOUT_MS_ENV",
    "LOCAL_DB_PATH_ENV",
    "LOCAL_RUNTIME_CONTROL_SOCKET_DIRNAME",
    "LOCAL_RUNTIME_CONTROL_SOCKET_FILENAME",
    "MAIN_PROCESS_PID_ENV",
    "build_local_runtime_control_socket_path",
    "read_local_runtime_artifact_root",
    "read_local_runtime_control_socket_path",
    "read_local_runtime_db_config",
    "read_local_backend_bound_host",
    "read_local_backend_bound_port",
    "read_helper_instance_id",
    "read_main_process_pid",
]
