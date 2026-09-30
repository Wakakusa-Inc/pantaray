from __future__ import annotations

import mimetypes
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from pantaray_agents.schema.agent.base import JSONValue
from pantaray_agents.security.image_media_types import IMAGE_MIME_TYPES

from .attachment_reference import build_workspace_file_attachment
from .broker_common import (
    BrokerContext,
    BrokerPolicyError,
    ensure_session_capabilities,
)
from .broker_direct_read_document import (
    document_format,
    read_document,
    reject_legacy_document,
)
from .broker_direct_read_page import (
    DEFAULT_READ_LIMIT,
    bound_text_page,
    text_page_output,
)
from .broker_direct_read_text import read_text_lines
from .broker_outcome import UnprojectedBrokerToolOutcome
from .broker_protocol import ValidatedReadRequest
from .read_path_resolver import (
    ReadTarget,
    action_reference_paths,
    resolve_read_target,
)
from .tool_path_policy import hidden_read_path_filter

SAMPLE_BYTES = 4_096
MAX_ATTACHMENT_BYTES = 20 * 1024 * 1024
READ_BINARY_FILE_UNSUPPORTED = "READ_BINARY_FILE_UNSUPPORTED"
READ_NOT_A_REGULAR_FILE = "READ_NOT_A_REGULAR_FILE"
READ_ATTACHMENT_TOO_LARGE = "READ_ATTACHMENT_TOO_LARGE"
READ_START_UNIT_UNSUPPORTED = "READ_START_UNIT_UNSUPPORTED"
READ_DIRECTORY_SCAN_LIMIT = 20_000
READ_DIRECTORY_SCAN_BUDGET_RETRY_HINT = (
    "Use a narrower directory path, or use list/glob with a more specific base path "
    "before reading this directory again."
)
READ_DIRECTORY_PAGE_LIMIT_RETRY_HINT = "Continue with offset=next_offset."

_BINARY_EXTENSIONS = frozenset(
    {
        ".7z",
        ".a",
        ".bin",
        ".class",
        ".dat",
        ".dll",
        ".exe",
        ".gz",
        ".jar",
        ".lib",
        ".o",
        ".obj",
        ".pyc",
        ".pyo",
        ".so",
        ".tar",
        ".war",
        ".wasm",
        ".zip",
    }
)
_INTERNAL_DIRECTORY_NAMES = frozenset({".runtime-temp", ".venv"})


@dataclass(frozen=True, slots=True)
class DirectoryReadResult:
    entries: list[dict[str, JSONValue]]
    next_offset: int | None
    truncated: bool
    truncation_reason: str | None
    retry_hint: str | None


def run_read_executor(
    *,
    context: BrokerContext,
    request: ValidatedReadRequest,
) -> UnprojectedBrokerToolOutcome:
    ensure_session_capabilities(context=context)
    target = resolve_read_target(context=context, raw_path=request.path)
    if target.real_path.is_dir():
        if not target.allow_directory:
            raise BrokerPolicyError("read.path must reference an existing file")
        return _read_directory(context=context, target=target, request=request)
    return _read_file(target=target, request=request)


def _read_file(
    *,
    target: ReadTarget,
    request: ValidatedReadRequest,
) -> UnprojectedBrokerToolOutcome:
    sample = read_leading_bytes(target, limit=SAMPLE_BYTES)
    mime_type = _sniff_image_mime(filepath=target.real_path, sample=sample)
    if mime_type is not None:
        _reject_start_unit(request)
        byte_size = target.real_path.stat().st_size
        if byte_size > MAX_ATTACHMENT_BYTES:
            raise BrokerPolicyError(
                (
                    f"Attachment is too large to read: {target.display_path} "
                    f"({byte_size} bytes > {MAX_ATTACHMENT_BYTES} bytes)"
                ),
                code=READ_ATTACHMENT_TOO_LARGE,
            )
        payload = _read_attachment_payload(target=target)
        workspace_attachment = build_workspace_file_attachment(
            canonical_root_path=target.canonical_root_path,
            root_relative_path=target.root_relative_path,
            display_path=target.display_path,
            mime_type=mime_type,
            payload=payload,
        )
        return UnprojectedBrokerToolOutcome(
            status="success",
            output={
                "kind": "attachment",
                "path": target.display_path,
                "mime_type": mime_type,
                "message": "Image read successfully",
                "attachments": [
                    {
                        "type": "file",
                        "mime_type": mime_type,
                        "path": target.display_path,
                        "ref": workspace_attachment.ref,
                        "byte_size": workspace_attachment.byte_size,
                    }
                ],
            },
            search_text=None,
            file_paths=(target.display_path,),
            file_reference_paths=action_reference_paths(target),
            attachments=(
                {
                    "type": "file",
                    "source_kind": "workspace_file",
                    "ref": workspace_attachment.ref,
                    "blob_ref": workspace_attachment.blob_ref,
                    "display_path": target.display_path,
                    "workspace_root_path": str(
                        workspace_attachment.canonical_root_path
                    ),
                    "workspace_relative_path": (
                        workspace_attachment.root_relative_path
                    ),
                    "mime_type": mime_type,
                    "byte_size": workspace_attachment.byte_size,
                    "sha256": workspace_attachment.sha256,
                },
            ),
        )
    reject_legacy_document(target)
    extracted_format = document_format(filepath=target.real_path, sample=sample)
    if extracted_format is not None:
        return read_document(
            target=target, request=request, document_format=extracted_format
        )
    if _is_binary_file(filepath=target.real_path, sample=sample):
        raise BrokerPolicyError(
            f"Cannot read binary file: {target.display_path}",
            code=READ_BINARY_FILE_UNSUPPORTED,
        )
    _reject_start_unit(request)

    offset = request.offset or 1
    column = request.column or 1
    limit = request.limit or DEFAULT_READ_LIMIT
    result = read_text_lines(
        filepath=target.real_path,
        offset=offset,
        column=column,
        limit=limit,
    )
    output = bound_text_page(
        text_page_output(
            kind="file",
            path=target.display_path,
            offset=offset,
            column=column,
            result=result,
        ),
        content=result.content,
        offset=offset,
        column=column,
    )
    return UnprojectedBrokerToolOutcome(
        status="success",
        output=output,
        search_text=cast(str, output["content"]),
        file_paths=(target.display_path,),
        file_reference_paths=action_reference_paths(target),
    )


def _read_directory(
    *,
    context: BrokerContext,
    target: ReadTarget,
    request: ValidatedReadRequest,
) -> UnprojectedBrokerToolOutcome:
    if request.column not in {None, 1}:
        raise BrokerPolicyError("read.column is valid only for text files")
    _reject_start_unit(request)
    offset = request.offset or 1
    limit = request.limit or DEFAULT_READ_LIMIT
    result = _read_bounded_directory_entries(
        context=context,
        target=target,
        offset=offset,
        limit=limit,
    )
    search_text = "\n".join(
        f"{entry['name']}/" if entry["kind"] == "directory" else str(entry["name"])
        for entry in result.entries
    )
    return UnprojectedBrokerToolOutcome(
        status="success",
        output={
            "kind": "directory",
            "path": target.display_path,
            "entries": cast(JSONValue, result.entries),
            "offset": offset,
            "next_offset": result.next_offset,
            "truncated": result.truncated,
            "truncation_reason": result.truncation_reason,
            "retry_hint": result.retry_hint,
        },
        search_text=search_text,
        file_paths=(target.display_path,),
        file_reference_paths=(),
    )


def _read_bounded_directory_entries(
    *,
    context: BrokerContext,
    target: ReadTarget,
    offset: int,
    limit: int,
) -> DirectoryReadResult:
    entries: list[dict[str, JSONValue]] = []
    visible_index = 0
    scanned = 0
    is_hidden = hidden_read_path_filter(context)
    with os.scandir(target.real_path) as iterator:
        for child in iterator:
            scanned += 1
            if scanned > READ_DIRECTORY_SCAN_LIMIT:
                return DirectoryReadResult(
                    entries=entries,
                    next_offset=(offset + len(entries) if entries else None),
                    truncated=True,
                    truncation_reason="scan_budget",
                    retry_hint=(
                        READ_DIRECTORY_SCAN_BUDGET_RETRY_HINT if not entries else None
                    ),
                )
            entry = _directory_entry(child, is_hidden=is_hidden, target=target)
            if entry is None:
                continue
            visible_index += 1
            if visible_index < offset:
                continue
            if len(entries) >= limit:
                return DirectoryReadResult(
                    entries=entries,
                    next_offset=offset + len(entries),
                    truncated=True,
                    truncation_reason="page_limit",
                    retry_hint=READ_DIRECTORY_PAGE_LIMIT_RETRY_HINT,
                )
            entries.append(entry)
    return DirectoryReadResult(
        entries=entries,
        next_offset=None,
        truncated=False,
        truncation_reason=None,
        retry_hint=None,
    )


def _directory_entry(
    child: os.DirEntry[str],
    *,
    is_hidden: Callable[[Path], bool],
    target: ReadTarget,
) -> dict[str, JSONValue] | None:
    if child.name in _INTERNAL_DIRECTORY_NAMES:
        return None
    child_path = Path(child.path)
    try:
        if child.is_symlink():
            if not target.allow_symlink_directory_entries:
                return None
        if is_hidden(child_path):
            return None
        kind = "directory" if child.is_dir() else "file"
    except OSError:
        return None
    return {"name": child.name, "kind": kind}


def _reject_start_unit(request: ValidatedReadRequest) -> None:
    """Refuse a unit cursor on a target that has no units to count.

    Only an extracted document numbers what it returns in pages, sheets, slides
    or cells; reading a text file, an image or a directory from a unit would
    silently ignore the argument the caller meant to steer the read with.
    """

    if request.start_unit is None:
        return
    raise BrokerPolicyError(
        "read.start_unit is valid only for a PDF, .docx, .xlsx, .pptx or "
        ".ipynb document",
        code=READ_START_UNIT_UNSUPPORTED,
        fix_hint=(
            "Read this path again without start_unit, and use offset to "
            "continue from an earlier result."
        ),
    )


def read_leading_bytes(target: ReadTarget, *, limit: int) -> bytes:
    """The first ``limit`` bytes of a regular file, opened so it cannot block.

    Every read starts here, before the file's kind is known. A FIFO with no
    writer blocks a plain open forever, on a thread nothing can stop, and the
    one Action worker with it; O_NONBLOCK returns at once and the descriptor
    says what was opened. The text and document branches open their files the
    same way.
    """

    descriptor = os.open(
        target.real_path,
        os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK,
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise BrokerPolicyError(
                f"Cannot read {target.display_path}: it is not a regular file",
                code=READ_NOT_A_REGULAR_FILE,
            )
        with open(descriptor, "rb", closefd=False) as handle:
            return handle.read(limit)
    finally:
        os.close(descriptor)


def _sniff_image_mime(*, filepath: Path, sample: bytes) -> str | None:
    """The media type of an image, which is the only file returned as itself.

    Every other binary this tool reads is turned into text, so an image is the
    one file whose bytes have to reach the model to be understood at all.
    """

    if sample.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if sample.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if sample.startswith(b"GIF87a") or sample.startswith(b"GIF89a"):
        return "image/gif"
    if sample.startswith(b"RIFF") and sample[8:12] == b"WEBP":
        return "image/webp"
    guessed, _encoding = mimetypes.guess_type(filepath.name)
    return guessed if guessed in IMAGE_MIME_TYPES else None


def _read_attachment_payload(*, target: ReadTarget) -> bytes:
    payload = read_leading_bytes(target, limit=MAX_ATTACHMENT_BYTES + 1)
    if len(payload) > MAX_ATTACHMENT_BYTES:
        raise BrokerPolicyError(
            (
                f"Attachment is too large to read: {target.display_path} "
                f"(> {MAX_ATTACHMENT_BYTES} bytes)"
            ),
            code=READ_ATTACHMENT_TOO_LARGE,
        )
    return payload


def _is_binary_file(*, filepath: Path, sample: bytes) -> bool:
    if filepath.suffix.lower() in _BINARY_EXTENSIONS:
        return True
    if not sample:
        return False
    non_printable = 0
    for byte in sample:
        if byte == 0:
            return True
        if byte < 9 or (byte > 13 and byte < 32):
            non_printable += 1
    return non_printable / len(sample) > 0.3


__all__ = ["SAMPLE_BYTES", "read_leading_bytes", "run_read_executor"]
