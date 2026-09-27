import asyncio
import contextlib
import hashlib
import json
import os
import tempfile
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from pantaray_agents.local_runtime.app_runtime_verification import (
    LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV,
)
from pantaray_agents.local_runtime.context import source_reader
from pantaray_agents.local_runtime.context.source_gate import (
    ActiveSource,
    SourceGate,
    SourceInvalidated,
)
from pantaray_agents.local_runtime.context.source_protocol import (
    MAX_EVIDENCE_BYTES,
    MAX_PAGE_BYTES,
    EvidenceOrigin,
    EvidenceReadRequest,
    PageReadRequest,
    PageResponse,
)
from pantaray_agents.local_runtime.context.source_reader import (
    ProtocolFailure,
    ReadOverLimit,
    ReadTimeout,
    SourceManifestError,
    SourceReader,
    load_zanei_runtime_manifest,
)
from pantaray_agents.schema.context_source import SourceBinding

pytestmark = pytest.mark.asyncio

CHILD = r"""#!/usr/bin/env python3
import json
import os
import socket
import sys

request = json.loads(sys.stdin.buffer.readline())
capture = {
    "argv": sys.argv[1:],
    "request": request,
    "service": os.environ.get("ZANEI_KEYCHAIN_SERVICE"),
    "label": os.environ.get("ZANEI_KEYCHAIN_LABEL"),
    "no_prompt": os.environ.get("ZANEI_KEYCHAIN_NO_PROMPT"),
    "store_key": os.environ.get("ZANEI_STORE_KEY_FILE"),
}
with open(os.environ["P04C_CAPTURE"], "w", encoding="utf-8") as output:
    json.dump(capture, output)

mode = os.environ["P04C_MODE"]
control_path = os.environ.get("P04C_CONTROL")
if control_path:
    control = socket.socket(socket.AF_UNIX)
    control.connect(control_path)
    control.sendall(f"READY {os.getpid()}\n".encode())
    if mode in {"wait", "controlled"}:
        control.recv(1)

if request["kind"] == "page":
    observations = []
    coverage = {"after": 0, "through": 0}
    if mode == "page_over":
        absent = {"kind": "absent"}
        observations = [{
            "append_sequence": 1,
            "id": "event-1",
            "ts": "2026-09-06T00:00:00Z",
            "source": {"kind": "value", "text": "x" * (2 * 1024 * 1024)},
            "event_type": absent,
            "bundle_id": absent,
            "app_name": absent,
            "pid": None,
            "window_title": absent,
            "window_id": None,
        }]
        coverage = {"after": 0, "through": 1}
    response = {
        "protocol_version": 1,
        "kind": "page",
        "store_identity": "store-1",
        "observations": observations,
        "next_cursor": "cursor-1",
        "upper_bound": "upper-1",
        "has_more": False,
        "coverage": coverage,
    }
else:
    if mode == "evidence_over":
        text = "x" * (256 * 1024)
        content = {
            "kind": "text", "text": text, "start": 0,
            "end": len(text), "total_bytes": len(text), "remaining": None,
        }
    else:
        content = {"kind": "absent"}
    response = {
        "protocol_version": 1,
        "kind": "evidence",
        "origin": request["origin"],
        "content": content,
        "metadata": {
            "event_type": "content.snapshot",
            "payload_without_text": {},
            "redaction_applied": False,
            "truncated": False,
        },
    }
sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
sys.stdout.flush()
"""


@dataclass
class ControlBarrier:
    path: Path = field(
        default_factory=lambda: Path(tempfile.gettempdir()) / f"p04c-{uuid4().hex}.sock"
    )
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    pid: int | None = None
    writer: asyncio.StreamWriter | None = None
    server: asyncio.Server | None = None

    async def start(self) -> None:
        self.server = await asyncio.start_unix_server(self._accept, path=self.path)

    async def _accept(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        line = await reader.readline()
        marker, raw_pid = line.decode().strip().split()
        assert marker == "READY"
        self.pid = int(raw_pid)
        self.writer = writer
        self.ready.set()

    async def release(self) -> None:
        assert self.writer is not None
        self.writer.write(b"1")
        await self.writer.drain()

    async def close(self) -> None:
        if self.writer is not None:
            self.writer.close()
            await self.writer.wait_closed()
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        self.path.unlink(missing_ok=True)


def _binding() -> SourceBinding:
    return SourceBinding(
        store_id="store-1",
        protocol_version=1,
        user_id="利用者@example.jp",
        epoch=uuid4(),
        policy_revision="policy-1",
    )


async def _activate(gate: SourceGate) -> ActiveSource:
    async with gate.turn():
        gate.activate(_binding())
        source = gate.current("利用者@example.jp")
        assert source is not None
        return source


def _page_request() -> PageReadRequest:
    return PageReadRequest(cursor=None, upper_bound=None, limit=1)


def _evidence_request(store_identity: str = "store-1") -> EvidenceReadRequest:
    return EvidenceReadRequest(
        origin=EvidenceOrigin(
            store_identity=store_identity,
            append_sequence=1,
            event_id="event-1",
            observed_at="2026-09-06T00:00:00Z",
            field="text",
        ),
        start=0,
        end=None,
    )


def _install_runtime(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    mode: str = "success",
    barrier: ControlBarrier | None = None,
) -> tuple[Path, Path, Path]:
    executable = tmp_path / "zanei"
    executable.write_text(CHILD, encoding="utf-8")
    executable.chmod(0o700)
    subject_root = tmp_path / "app-context"
    capture = tmp_path / "capture.json"
    manifest = tmp_path / "runtime.json"
    manifest.write_text(
        json.dumps(
            {
                "python_path": "/trusted/python",
                "zanei": {
                    "executable_path": str(executable),
                    "executable_sha256": hashlib.sha256(
                        executable.read_bytes()
                    ).hexdigest(),
                    "protocol_version": 1,
                    "subject_root": str(subject_root),
                    "keychain_service_prefix": "app/service",
                    "keychain_label_prefix": "Pantaray Context",
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv(LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV, str(manifest))
    monkeypatch.setenv("P04C_CAPTURE", str(capture))
    monkeypatch.setenv("P04C_MODE", mode)
    monkeypatch.setenv("ZANEI_STORE_KEY_FILE", "/wrong/key")
    if barrier is not None:
        monkeypatch.setenv("P04C_CONTROL", str(barrier.path))
    return executable, subject_root, capture


async def test_reader_uses_manifest_bound_paths_argv_and_keychain(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, subject_root, capture_path = _install_runtime(tmp_path, monkeypatch)
    gate = SourceGate()
    source = await _activate(gate)

    response = await SourceReader(gate).read_page(source, _page_request())

    assert isinstance(response, PageResponse)
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    suffix = hashlib.sha256(source.binding.user_id.encode()).hexdigest()
    subject_dir = subject_root / "subjects" / suffix
    assert capture["argv"] == [
        "--config",
        str(subject_dir / "config.toml"),
        "--store",
        str(subject_dir / "store.sqlite3"),
        "--quiet",
        "context-read",
    ]
    assert capture["request"] == _page_request().model_dump(mode="json")
    assert capture["service"] == f"app/service.{suffix}"
    assert capture["label"] == f"Pantaray Context.{suffix}"
    assert capture["no_prompt"] == "1"
    assert capture["store_key"] is None


@pytest.mark.parametrize(
    ("mode", "read_request", "limit"),
    [
        ("page_over", _page_request(), MAX_PAGE_BYTES),
        ("evidence_over", _evidence_request(), MAX_EVIDENCE_BYTES),
    ],
)
async def test_valid_json_over_output_budget_is_rejected_before_decode(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    mode: str,
    read_request: PageReadRequest | EvidenceReadRequest,
    limit: int,
) -> None:
    barrier = ControlBarrier()
    await barrier.start()
    _install_runtime(tmp_path, monkeypatch, mode=mode, barrier=barrier)
    gate = SourceGate()
    source = await _activate(gate)
    reader = SourceReader(gate)
    task: asyncio.Task[object] | None = None
    try:
        if isinstance(read_request, PageReadRequest):
            task = asyncio.create_task(reader.read_page(source, read_request))
        else:
            task = asyncio.create_task(reader.read_evidence(source, read_request))
        await asyncio.wait_for(barrier.ready.wait(), 3)
        async with asyncio.timeout(3):
            result = await task
        assert result == ReadOverLimit(limit)
        assert barrier.pid is not None
        with pytest.raises(ProcessLookupError):
            os.kill(barrier.pid, 0)
    finally:
        if task is not None and not task.done():
            task.cancel()
        if task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        await barrier.close()


async def test_timeout_after_child_ready_reaps_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = ControlBarrier()
    await barrier.start()
    _install_runtime(tmp_path, monkeypatch, mode="wait", barrier=barrier)
    gate = SourceGate()
    source = await _activate(gate)
    real_timeout = asyncio.timeout
    deadlines: list[asyncio.Timeout] = []

    def capture_timeout(delay: float | None) -> asyncio.Timeout:
        deadline = real_timeout(delay)
        deadlines.append(deadline)
        return deadline

    monkeypatch.setattr(source_reader.asyncio, "timeout", capture_timeout)
    task = asyncio.create_task(SourceReader(gate).read_page(source, _page_request()))
    try:
        await asyncio.wait_for(barrier.ready.wait(), 3)
        assert deadlines and barrier.pid is not None
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        assert await task == ReadTimeout()
        with pytest.raises(ProcessLookupError):
            os.kill(barrier.pid, 0)
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, SourceInvalidated):
            await task
        await barrier.close()


async def test_deadline_includes_initial_gate_wait(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = SourceGate()
    source = await _activate(gate)
    turn_held = asyncio.Event()
    release_turn = asyncio.Event()

    async def hold_turn() -> None:
        async with gate.turn():
            turn_held.set()
            await release_turn.wait()

    holder = asyncio.create_task(hold_turn())
    await turn_held.wait()
    real_timeout = asyncio.timeout
    created = asyncio.Event()
    deadlines: list[asyncio.Timeout] = []

    def capture_timeout(delay: float | None) -> asyncio.Timeout:
        deadlines.append(deadline := real_timeout(delay))
        created.set()
        return deadline

    monkeypatch.setattr(source_reader.asyncio, "timeout", capture_timeout)
    task = asyncio.create_task(SourceReader(gate).read_page(source, _page_request()))
    try:
        await asyncio.wait_for(created.wait(), 1)
        deadlines[0].reschedule(asyncio.get_running_loop().time())
        assert await task == ReadTimeout()
    finally:
        if not task.done():
            task.cancel()
        release_turn.set()
        await holder
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def test_cancellation_after_child_ready_propagates_and_reaps_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = ControlBarrier()
    await barrier.start()
    _install_runtime(tmp_path, monkeypatch, mode="wait", barrier=barrier)
    gate = SourceGate()
    source = await _activate(gate)
    task = asyncio.create_task(SourceReader(gate).read_page(source, _page_request()))
    try:
        await asyncio.wait_for(barrier.ready.wait(), 3)
        assert barrier.pid is not None
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        with pytest.raises(ProcessLookupError):
            os.kill(barrier.pid, 0)
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, SourceInvalidated):
            await task
        await barrier.close()


async def test_delayed_revoke_callback_cannot_launch_invalid_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, _, capture = _install_runtime(tmp_path, monkeypatch)
    gate = SourceGate()
    source = await _activate(gate)
    original_guard = gate.guard
    original_cancel = gate._cancel_tracked
    launch_waiting = asyncio.Event()
    launch_release = asyncio.Event()
    callbacks: list[tuple[UUID, asyncio.Task[object]]] = []
    guard_calls = 0

    @asynccontextmanager
    async def delayed_guard(candidate: ActiveSource) -> AsyncIterator[None]:
        nonlocal guard_calls
        guard_calls += 1
        if guard_calls == 2:
            launch_waiting.set()
            await launch_release.wait()
        async with original_guard(candidate):
            yield

    def delay_cancel(token: UUID, task: asyncio.Task[object]) -> None:
        callbacks.append((token, task))

    monkeypatch.setattr(gate, "guard", delayed_guard)
    monkeypatch.setattr(gate, "_cancel_tracked", delay_cancel)
    task = asyncio.create_task(SourceReader(gate).read_page(source, _page_request()))
    try:
        await asyncio.wait_for(launch_waiting.wait(), 3)
        async with gate.turn():
            gate.revoke(source.binding.user_id)
        launch_release.set()
        with pytest.raises(SourceInvalidated):
            await task
        assert not capture.exists()
        assert callbacks
        original_cancel(*callbacks[0])
    finally:
        launch_release.set()
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, SourceInvalidated):
            await task


async def test_response_is_rejected_when_revoke_callback_is_delayed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    barrier = ControlBarrier()
    await barrier.start()
    _install_runtime(tmp_path, monkeypatch, mode="controlled", barrier=barrier)
    gate = SourceGate()
    source = await _activate(gate)
    original_cancel = gate._cancel_tracked
    callbacks: list[tuple[UUID, asyncio.Task[object]]] = []
    monkeypatch.setattr(
        gate,
        "_cancel_tracked",
        lambda token, task: callbacks.append((token, task)),
    )
    task = asyncio.create_task(SourceReader(gate).read_page(source, _page_request()))
    try:
        await asyncio.wait_for(barrier.ready.wait(), 3)
        async with gate.turn():
            gate.revoke(source.binding.user_id)
        await barrier.release()
        with pytest.raises(SourceInvalidated):
            await task
        assert callbacks
        original_cancel(*callbacks[0])
    finally:
        if not task.done():
            task.cancel()
        with contextlib.suppress(asyncio.CancelledError, SourceInvalidated):
            await task
        await barrier.close()


async def test_evidence_origin_is_rejected_before_manifest_or_launch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV, raising=False)
    gate = SourceGate()
    source = await _activate(gate)

    result = await SourceReader(gate).read_evidence(
        source, _evidence_request("other-store")
    )

    assert result == ProtocolFailure(
        "request store identity does not match source binding"
    )


async def test_manifest_hash_mismatch_fails_without_launch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    executable, _, capture = _install_runtime(tmp_path, monkeypatch)
    executable.write_text(CHILD + "\n# changed", encoding="utf-8")
    gate = SourceGate()
    source = await _activate(gate)

    result = await SourceReader(gate).read_page(source, _page_request())

    assert result == ProtocolFailure("zanei executable hash does not match manifest")
    assert not capture.exists()


async def test_manifest_requires_zanei_section(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "zanei"
    executable.write_text(CHILD, encoding="utf-8")
    manifest = tmp_path / "runtime.json"
    manifest.write_text(json.dumps({"python_path": str(executable)}), encoding="utf-8")

    with pytest.raises(SourceManifestError):
        load_zanei_runtime_manifest(manifest_path=manifest)


@pytest.mark.parametrize(
    "change",
    [
        {"protocol_version": True},
        {"unexpected": "rejected"},
    ],
)
async def test_manifest_rejects_invalid_zanei_fields(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    change: dict[str, object],
) -> None:
    _install_runtime(tmp_path, monkeypatch)
    manifest = Path(os.environ[LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV])
    payload = json.loads(manifest.read_text(encoding="utf-8"))
    payload["zanei"].update(change)
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SourceManifestError):
        load_zanei_runtime_manifest(manifest_path=manifest)
