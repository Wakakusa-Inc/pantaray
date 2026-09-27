"""Start the local backend helper the way Electron main does, in an isolated root.

`localBackendHelperManager.ts` spawns `python -m pantaray_agents --host <loopback>
--port 0` with the helper instance id and the main process pid in the environment,
then polls the control socket until a `status` reply carries its own instance id.
This module does the same from Python, against a throwaway runtime root, so a live
check never touches the developer's own Pantaray data.

Provider secrets never reach the helper environment: `runtime/bootstrap.py` refuses
to start when one is set, because the control socket is the only way in (design 6.2).
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import socket
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONTROL_SOCKET_DIRNAME = "local-backend"
CONTROL_SOCKET_FILENAME = "control.sock"
HELPER_READY_TIMEOUT_SECONDS = 90.0
HELPER_READY_POLL_SECONDS = 0.2
HELPER_TERMINATION_TIMEOUT_SECONDS = 15.0
CONTROL_REQUEST_TIMEOUT_SECONDS = 30.0
# The runtime routes every provider call through the control socket, so these URLs
# are only here to satisfy the cloud-boundary env check and must never resolve.
UNUSED_PROXY_URLS = {
    "LLM_PROXY_URL": "https://unused.invalid/v1/llm/proxy",
    "WEB_TOOLS_PROXY_URL": "https://unused.invalid/v1/web/proxy",
}
PROVIDER_SECRET_ENVS = ("GEMINI_API_KEY", "OPENAI_API_KEY", "TAVILY_API_KEY")


class HelperStartError(RuntimeError):
    """The helper never reached a `status` reply that this process owns."""


@dataclass(frozen=True, slots=True)
class HelperHandle:
    root: Path
    socket_path: Path
    process: subprocess.Popen[bytes]
    instance_id: str
    local_api_token: str
    owner_id: str
    base_url: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_app_runtime_manifest(*, root: Path, python_path: Path) -> Path:
    """The manifest `app_runtime_verification` checks the helper interpreter against."""
    manifest_path = root / "app-runtime-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "python_path": str(python_path),
                "python_version": platform.python_version(),
                "python_sha256": _sha256(python_path),
            }
        ),
        encoding="utf-8",
    )
    return manifest_path


def build_helper_env(
    *, root: Path, agents_root: Path, manifest_path: Path, instance_id: str
) -> dict[str, str]:
    env = {
        key: value
        for key, value in os.environ.items()
        if key not in PROVIDER_SECRET_ENVS
    }
    env.update(
        {
            "NODE_ENV": "development",
            "USE_MOCKS": "false",
            "LOG_LEVEL": "INFO",
            "LOG_FILE_PATH": str(root / "agent.log"),
            "ALLOWED_ORIGINS": "http://localhost:3001",
            "ALLOWED_HOSTS": "localhost,127.0.0.1",
            "LOCAL_DB_PATH": str(root / "runtime.sqlite3"),
            "LOCAL_DB_BUSY_TIMEOUT_MS": "5000",
            "LOCAL_ARTIFACT_ROOT": str(root / "artifacts"),
            "LOCAL_APP_RUNTIME_MANIFEST_PATH": str(manifest_path),
            "PANTARAY_HELPER_INSTANCE_ID": instance_id,
            "PANTARAY_MAIN_PROCESS_PID": str(os.getpid()),
            "PYTHONPYCACHEPREFIX": str(root / "pycache"),
            "PYTHONPATH": os.pathsep.join(
                (
                    str(agents_root / "src"),
                    str(agents_root / "packages" / "pantaray-llm" / "src"),
                )
            ),
            **UNUSED_PROXY_URLS,
        }
    )
    return env


def control_request(
    socket_path: Path, operation: str, payload: dict[str, Any]
) -> dict[str, Any]:
    """One newline-delimited JSON request, exactly as `localBackendSessionSync.ts` sends."""
    request = json.dumps({"operation": operation, "payload": payload}).encode("utf-8")
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(CONTROL_REQUEST_TIMEOUT_SECONDS)
        client.connect(str(socket_path))
        client.sendall(request + b"\n")
        buffer = b""
        while b"\n" not in buffer:
            chunk = client.recv(4096)
            if not chunk:
                raise HelperStartError("control socket closed before replying")
            buffer += chunk
    response: dict[str, Any] = json.loads(buffer.split(b"\n", 1)[0])
    if response.get("ok") is not True:
        raise HelperStartError(
            f"control request {operation} failed: "
            f"{response.get('error_code')}: {response.get('message')}"
        )
    return response


def start_helper(*, root: Path, agents_root: Path, log_path: Path) -> HelperHandle:
    root.mkdir(parents=True, exist_ok=True)
    # The helper runs the interpreter this script runs -- the venv one, so that
    # uvicorn and the rest resolve -- while the manifest records the path
    # `verify_app_runtime_python` compares against, which is that venv symlink
    # resolved to the real interpreter.
    manifest_path = write_app_runtime_manifest(
        root=root, python_path=Path(sys.executable).resolve()
    )
    instance_id = str(uuid.uuid4())
    socket_path = root / CONTROL_SOCKET_DIRNAME / CONTROL_SOCKET_FILENAME
    stdio = log_path.open("wb")
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "pantaray_agents",
            "--host",
            "127.0.0.1",
            "--port",
            "0",
        ],
        cwd=str(agents_root),
        env=build_helper_env(
            root=root,
            agents_root=agents_root,
            manifest_path=manifest_path,
            instance_id=instance_id,
        ),
        stdout=stdio,
        stderr=subprocess.STDOUT,
    )
    try:
        status = _await_owned_status(
            process=process, socket_path=socket_path, instance_id=instance_id
        )
    except BaseException:
        terminate_helper(process)
        raise
    finally:
        stdio.close()
    return HelperHandle(
        root=root,
        socket_path=socket_path,
        process=process,
        instance_id=instance_id,
        local_api_token=status["local_api_token"],
        owner_id=status["active_owner_id"],
        base_url=f"http://{status['backend_host']}:{status['backend_port']}",
    )


def _await_owned_status(
    *, process: subprocess.Popen[bytes], socket_path: Path, instance_id: str
) -> dict[str, Any]:
    deadline = time.monotonic() + HELPER_READY_TIMEOUT_SECONDS
    last_error: Exception | None = None
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise HelperStartError(
                f"helper exited before becoming ready: code={process.returncode}"
            )
        try:
            status = control_request(socket_path, "status", {})
        except (OSError, HelperStartError) as error:
            last_error = error
        else:
            if status["helper_instance_id"] == instance_id:
                return status
            last_error = HelperStartError(
                "control socket is owned by another helper instance"
            )
        time.sleep(HELPER_READY_POLL_SECONDS)
    raise HelperStartError(f"helper did not become ready: {last_error}")


def terminate_helper(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=HELPER_TERMINATION_TIMEOUT_SECONDS)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=HELPER_TERMINATION_TIMEOUT_SECONDS)
