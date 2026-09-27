"""Manifest-bound subprocess lifecycle for local Zanei context reads."""

import asyncio
import hashlib
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from pantaray_agents.local_runtime.app_runtime_verification import (
    LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV,
)

from .source_gate import ActiveSource, SourceGate
from .source_protocol import (
    MAX_EVIDENCE_BYTES,
    MAX_PAGE_BYTES,
    PROTOCOL_VERSION,
    EvidenceReadRequest,
    PageReadRequest,
    ProtocolError,
    ReadRequest,
    ReadResponse,
    decode_response,
    encode_request,
    validate_response_binding,
)

READ_DEADLINE_SECONDS = 10.0
READ_CHUNK_BYTES = 64 * 1024
STORE_KEY_FILE_ENV = "ZANEI_STORE_KEY_FILE"
KEYCHAIN_SERVICE_ENV = "ZANEI_KEYCHAIN_SERVICE"
KEYCHAIN_LABEL_ENV = "ZANEI_KEYCHAIN_LABEL"
KEYCHAIN_NO_PROMPT_ENV = "ZANEI_KEYCHAIN_NO_PROMPT"


class SourceManifestError(ValueError):
    """The trusted runtime manifest cannot identify a usable Zanei binary."""


@dataclass(frozen=True, slots=True)
class SubjectRuntimePaths:
    config_path: Path
    store_path: Path
    keychain_service: str
    keychain_label: str


class ZaneiRuntimeManifest(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        strict=True,
        hide_input_in_errors=True,
    )

    executable_path: Path
    executable_sha256: Annotated[str, Field(pattern=r"^[0-9a-f]{64}$")]
    protocol_version: Annotated[
        int,
        Field(strict=True, ge=PROTOCOL_VERSION, le=PROTOCOL_VERSION),
    ]
    subject_root: Path
    keychain_service_prefix: Annotated[str, Field(strict=True, min_length=1)]
    keychain_label_prefix: Annotated[str, Field(strict=True, min_length=1)]

    @field_validator("executable_path", "subject_root")
    @classmethod
    def require_absolute_path(cls, value: Path) -> Path:
        if not value.is_absolute():
            raise ValueError("zanei runtime paths must be absolute")
        return value

    @field_validator("keychain_service_prefix", "keychain_label_prefix")
    @classmethod
    def require_environment_value(cls, value: str) -> str:
        if "\0" in value:
            raise ValueError("keychain identity prefix contains a null byte")
        return value

    @model_validator(mode="after")
    def require_executable_file(self) -> Self:
        try:
            executable = self.executable_path.resolve(strict=True)
        except OSError as exc:
            raise ValueError("zanei executable_path must exist") from exc
        if not executable.is_file():
            raise ValueError("zanei executable_path must reference a file")
        object.__setattr__(self, "executable_path", executable)
        return self

    def subject_paths(self, subject: str) -> SubjectRuntimePaths:
        if not subject:
            raise SourceManifestError("authenticated subject must not be empty")
        suffix = hashlib.sha256(subject.encode("utf-8")).hexdigest()
        subject_dir = self.subject_root / "subjects" / suffix
        return SubjectRuntimePaths(
            config_path=subject_dir / "config.toml",
            store_path=subject_dir / "store.sqlite3",
            keychain_service=f"{self.keychain_service_prefix}.{suffix}",
            keychain_label=f"{self.keychain_label_prefix}.{suffix}",
        )


class _RuntimeManifest(BaseModel):
    model_config = ConfigDict(
        extra="ignore",
        strict=True,
        hide_input_in_errors=True,
    )

    zanei: ZaneiRuntimeManifest


@dataclass(frozen=True, slots=True)
class ProtocolFailure:
    message: str


@dataclass(frozen=True, slots=True)
class ReadTimeout:
    pass


@dataclass(frozen=True, slots=True)
class ReadOverLimit:
    limit: int


type ReadFailure = ProtocolFailure | ReadTimeout | ReadOverLimit
type ReadResult = ReadResponse | ReadFailure


def load_zanei_runtime_manifest(*, manifest_path: Path) -> ZaneiRuntimeManifest:
    if not manifest_path.is_file():
        raise SourceManifestError(f"runtime manifest is not a file: {manifest_path}")
    try:
        return _RuntimeManifest.model_validate_json(manifest_path.read_bytes()).zanei
    except (OSError, ValueError) as exc:
        raise SourceManifestError(
            "runtime manifest has an invalid zanei section"
        ) from exc


def runtime_manifest_from_environment() -> ZaneiRuntimeManifest:
    raw_path = os.environ.get(LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV)
    if raw_path is None or not raw_path.strip():
        raise SourceManifestError(f"{LOCAL_APP_RUNTIME_MANIFEST_PATH_ENV} is required")
    return load_zanei_runtime_manifest(manifest_path=Path(raw_path))


def verify_executable_digest(manifest: ZaneiRuntimeManifest) -> None:
    try:
        with manifest.executable_path.open("rb") as executable:
            actual = hashlib.file_digest(executable, "sha256").hexdigest()
    except OSError as exc:
        raise SourceManifestError("zanei executable cannot be read") from exc
    if actual != manifest.executable_sha256:
        raise SourceManifestError("zanei executable hash does not match manifest")


def child_environment(paths: SubjectRuntimePaths) -> dict[str, str]:
    environment = dict(os.environ)
    environment.pop(STORE_KEY_FILE_ENV, None)
    environment[KEYCHAIN_SERVICE_ENV] = paths.keychain_service
    environment[KEYCHAIN_LABEL_ENV] = paths.keychain_label
    environment[KEYCHAIN_NO_PROMPT_ENV] = "1"
    return environment


class _OutputOverLimit(Exception):
    pass


class SourceReader:
    def __init__(self, gate: SourceGate) -> None:
        self._gate = gate

    async def read_page(
        self,
        source: ActiveSource,
        request: PageReadRequest,
    ) -> ReadResult:
        return await self._read(source, request, output_limit=MAX_PAGE_BYTES)

    async def read_evidence(
        self,
        source: ActiveSource,
        request: EvidenceReadRequest,
    ) -> ReadResult:
        return await self._read(source, request, output_limit=MAX_EVIDENCE_BYTES)

    async def _read(
        self,
        source: ActiveSource,
        request: ReadRequest,
        *,
        output_limit: int,
    ) -> ReadResult:
        process: asyncio.subprocess.Process | None = None
        try:
            async with asyncio.timeout(READ_DEADLINE_SECONDS):
                async with self._gate.track(source):
                    if (
                        isinstance(request, EvidenceReadRequest)
                        and request.origin.store_identity != source.binding.store_id
                    ):
                        raise ProtocolError(
                            "request store identity does not match source binding"
                        )
                    manifest = runtime_manifest_from_environment()
                    verify_executable_digest(manifest)
                    if manifest.protocol_version != source.binding.protocol_version:
                        raise ProtocolError(
                            "manifest protocol does not match source binding"
                        )
                    paths = manifest.subject_paths(source.binding.user_id)
                    request_bytes = encode_request(request)
                    async with self._gate.guard(source):
                        process = await asyncio.create_subprocess_exec(
                            str(manifest.executable_path),
                            "--config",
                            str(paths.config_path),
                            "--store",
                            str(paths.store_path),
                            "--quiet",
                            "context-read",
                            stdin=asyncio.subprocess.PIPE,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.DEVNULL,
                            env=child_environment(paths),
                        )
                    raw = await _exchange(process, request_bytes, output_limit)
                    response = decode_response(raw)
                    async with self._gate.guard(source):
                        validate_response_binding(
                            request,
                            response,
                            store_identity=source.binding.store_id,
                        )
                        return response
        except _OutputOverLimit:
            return ReadOverLimit(output_limit)
        except TimeoutError:
            return ReadTimeout()
        except (OSError, ProtocolError, SourceManifestError) as exc:
            return ProtocolFailure(str(exc))
        finally:
            await _reap(process)


async def _exchange(
    process: asyncio.subprocess.Process,
    request: bytes,
    output_limit: int,
) -> bytes:
    if process.stdin is None or process.stdout is None:
        raise ProtocolError("context-read pipes are unavailable")
    process.stdin.write(request)
    await process.stdin.drain()
    process.stdin.close()
    response = await _read_stdout_bounded(process.stdout, output_limit)
    if await process.wait() != 0:
        raise ProtocolError("context-read exited unsuccessfully")
    return response


async def _read_stdout_bounded(
    reader: asyncio.StreamReader,
    limit: int,
) -> bytes:
    chunks: list[bytes] = []
    size = 0
    while True:
        chunk = await reader.read(min(READ_CHUNK_BYTES, limit + 1 - size))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        size += len(chunk)
        if size > limit:
            raise _OutputOverLimit


async def _reap(process: asyncio.subprocess.Process | None) -> None:
    if process is None:
        return
    if process.returncode is None:
        try:
            process.kill()
        except ProcessLookupError:
            pass
    if process.stdout is not None:
        while await process.stdout.read(READ_CHUNK_BYTES):
            pass
    await process.wait()
