"""Prepare the helper request and its invocation-local generated script."""

from __future__ import annotations

import ipaddress
import os
import uuid
from pathlib import Path
from typing import cast

from ...runtime.runtime_env import (
    read_local_backend_bound_host,
    read_local_backend_bound_port,
)
from ..brokering.broker_protocol import ValidatedCommandRequest
from .command_sandbox_protocol import BrokerToSandboxCommandRequest
from .macos_runtime import app_python_runtime_root, toolchain_read_roots

GENERATED_PYTHON_SCRIPT_NAME = "generated_main.py"


def build_sandbox_request(
    *,
    request: ValidatedCommandRequest,
    temp_dir: Path,
) -> BrokerToSandboxCommandRequest:
    raw_host = read_local_backend_bound_host()
    host = ipaddress.ip_address("127.0.0.1" if raw_host == "localhost" else raw_host)
    port = read_local_backend_bound_port()
    # A wildcard listener is reachable on every interface; loopback also covers IPv6.
    address = (
        "*" if host.is_unspecified else "localhost" if host.is_loopback else str(host)
    )
    if isinstance(host, ipaddress.IPv6Address) and not (
        host.is_unspecified or host.is_loopback
    ):
        address = f"[{host}]"
    protected_backend_address = f"{address}:{port}"
    argv = _resolve_sandbox_argv(request=request, temp_dir=temp_dir)
    real_read_roots = _dedupe_root_strings(
        *request.real_read_roots,
        str(temp_dir),
    )
    real_write_roots = _dedupe_root_strings(
        *request.real_write_roots,
        str(temp_dir),
    )
    return BrokerToSandboxCommandRequest(
        request_id=str(uuid.uuid4()),
        action_id=request.action_id,
        execution_session_id=request.execution_session_id,
        tool_invocation_id=cast(str, request.tool_invocation_id),
        manifest_id=request.manifest_id,
        real_read_roots=real_read_roots,
        real_write_roots=real_write_roots,
        action_plan_path=request.action_plan_path,
        private_storage_roots=request.private_storage_roots,
        action_workspace_root=request.action_workspace_root,
        published_results_root=request.published_results_root,
        app_runtime_root=str(app_python_runtime_root(Path(request.app_runtime_python))),
        cwd=request.cwd,
        argv=argv,
        runtime_read_roots=_dedupe_root_strings(*toolchain_read_roots()),
        env={
            **request.env,
            "TMPDIR": str(temp_dir),
            "HOME": str(Path.home() if request.use_login_environment else temp_dir),
            "RUSTUP_HOME": os.environ.get("RUSTUP_HOME", str(Path.home() / ".rustup")),
        },
        timeout_ms=request.timeout_ms,
        stdout_max_bytes=request.stdout_max_bytes,
        stderr_max_bytes=request.stderr_max_bytes,
        temp_dir=str(temp_dir),
        temp_storage_limit_bytes=request.temp_storage_limit_bytes,
        network_policy=request.network_policy,
        use_login_environment=request.use_login_environment,
        protected_backend_address=protected_backend_address,
    )


def _dedupe_root_strings(*roots: str) -> list[str]:
    return list(dict.fromkeys(str(Path(root).resolve()) for root in roots))


def _resolve_sandbox_argv(
    *,
    request: ValidatedCommandRequest,
    temp_dir: Path,
) -> list[str]:
    if request.generated_python_code is None:
        return list(request.argv)
    script_path = temp_dir / GENERATED_PYTHON_SCRIPT_NAME
    script_path.write_text(request.generated_python_code, encoding="utf-8")
    return [request.argv[0], str(script_path), *request.argv[1:]]
