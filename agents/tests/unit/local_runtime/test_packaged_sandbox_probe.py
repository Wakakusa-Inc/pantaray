"""The packaged sandbox probe must build a request the command worker accepts.

The probe (frontend/scripts/verify-command-sandbox.py) runs only in the release
workflow, after build, signing and notarization, so a protocol change that
leaves it behind otherwise fails the release instead of the pull request.
"""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

from pantaray_agents.local_runtime.tooling.sandbox.command_sandbox_protocol import (
    decode_request,
    encode_message,
)
from pantaray_agents.local_runtime.tooling.sandbox.seatbelt_profiles import (
    render_seatbelt_profile,
)

PROBE_PATH = (
    Path(__file__).resolve().parents[4]
    / "frontend"
    / "scripts"
    / "verify-command-sandbox.py"
)


def _load_probe() -> ModuleType:
    spec = importlib.util.spec_from_file_location("packaged_sandbox_probe", PROBE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("enabled", [True, False])
def test_probe_request_passes_the_worker_decode_and_profile(
    tmp_path: Path, enabled: bool
) -> None:
    request = _load_probe().build_probe_request(
        workspace=tmp_path / "workspace",
        temporary=tmp_path / "temp",
        private=tmp_path / "private",
        enabled=enabled,
        ordinary_port=40_001,
        protected_port=40_002,
    )

    # The worker's own steps before it spawns sandbox-exec (macOS only).
    assert decode_request(encode_message(request).decode()) == request
    render_seatbelt_profile(request)
