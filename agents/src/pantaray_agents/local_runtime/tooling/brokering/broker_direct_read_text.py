from __future__ import annotations

import errno
import os
import stat
from dataclasses import dataclass
from io import StringIO
from typing import TextIO

from .broker_common import BrokerPolicyError

MAX_BYTES = 50 * 1024
MAX_LINE_LENGTH = 2_000
MAX_TOTAL_LINE_COUNT_BYTES = 512 * 1024
MAX_TEXT_SCAN_BYTES = 8 * 1024 * 1024
READ_SCAN_LIMIT_MESSAGE = (
    "Text scan limit reached before the requested position. "
    "Retry with a smaller offset or column."
)
READ_FILE_SCAN_LIMIT_RETRY_HINT = (
    "Text scan limit reached; this is partial content with no continuation. "
    "Use a smaller offset or column to read an earlier range."
)
READ_OFFSET_OUT_OF_RANGE = "READ_OFFSET_OUT_OF_RANGE"
READ_FILE_LINE_COUNT_BUDGET_RETRY_HINT = (
    "Use next_offset to continue reading. total_lines is unavailable because the "
    "file is too large to count safely in one read call."
)
READ_FILE_PAGE_LIMIT_RETRY_HINT = (
    "Continue with offset=next_offset and column=next_column."
)

_LINE_READ_AHEAD_CHARS = MAX_LINE_LENGTH + 1


@dataclass(frozen=True, slots=True)
class ReadLinesResult:
    content: str
    column: int
    total_lines: int | None
    end_line: int
    end_column: int
    next_offset: int | None
    next_column: int | None
    truncated: bool
    truncation_reason: str | None
    retry_hint: str | None


@dataclass(frozen=True, slots=True)
class TextLineRead:
    text: str
    fits_byte_budget: bool
    line_complete: bool
    stream_has_line_remainder: bool
    scanned_bytes: int
    consumed_chars: int


def read_text_descriptor_lines(
    *,
    descriptor: int,
    offset: int,
    limit: int,
    column: int = 1,
    max_bytes: int | None = None,
) -> ReadLinesResult:
    file_stat = os.fstat(descriptor)
    if not stat.S_ISREG(file_stat.st_mode):
        raise OSError(errno.EINVAL, "text descriptor is not a regular file")
    with open(descriptor, encoding="utf-8", newline="", closefd=False) as handle:
        return _read_text_lines(
            handle=handle,
            text_size_bytes=file_stat.st_size,
            offset=offset,
            limit=limit,
            column=column,
            max_bytes=MAX_BYTES if max_bytes is None else max_bytes,
        )


def read_text_value_lines(
    *,
    text: str,
    offset: int,
    limit: int,
    column: int = 1,
    max_bytes: int | None = None,
) -> ReadLinesResult:
    return _read_text_lines(
        handle=StringIO(text, newline=""),
        text_size_bytes=len(text.encode("utf-8")),
        offset=offset,
        limit=limit,
        column=column,
        max_bytes=MAX_BYTES if max_bytes is None else max_bytes,
    )


def _read_text_lines(
    *,
    handle: TextIO,
    text_size_bytes: int,
    offset: int,
    limit: int,
    column: int,
    max_bytes: int,
) -> ReadLinesResult:
    if column <= 0:
        raise ValueError("column must be positive")
    if max_bytes <= 0 or max_bytes > MAX_BYTES:
        raise ValueError(f"max_bytes must be within 1..{MAX_BYTES}")
    should_count_exact_total = text_size_bytes <= MAX_TOTAL_LINE_COUNT_BYTES
    content_lines: list[str] = []
    content_bytes = 0
    current_line = 0
    end_line = max(offset - 1, 0)
    end_column = 0
    next_offset: int | None = None
    next_column: int | None = None
    pending_current_line_remainder = False
    scanned_bytes = 0
    saw_eof = False
    scan_limit_reached = False
    while current_line < offset - 1:
        skipped_line = _read_bounded_text_line(
            handle,
            byte_budget=None,
            consume_remainder=True,
            scan_byte_budget=MAX_TEXT_SCAN_BYTES - scanned_bytes,
        )
        if skipped_line is None:
            saw_eof = True
            break
        current_line += 1
        scanned_bytes += skipped_line.scanned_bytes

    while len(content_lines) < limit:
        remaining_scan_bytes = MAX_TEXT_SCAN_BYTES - scanned_bytes
        remaining_bytes = max_bytes - content_bytes
        line = _read_bounded_text_line(
            handle,
            byte_budget=remaining_bytes,
            consume_remainder=False,
            start_column=column if current_line + 1 == offset else 1,
            scan_byte_budget=remaining_scan_bytes,
        )
        if line is None:
            saw_eof = True
            break
        current_line += 1
        scanned_bytes += line.scanned_bytes
        current_column = column if current_line == offset else 1
        scan_limit_reached = scanned_bytes >= MAX_TEXT_SCAN_BYTES
        if not line.fits_byte_budget:
            if scan_limit_reached:
                if not content_lines:
                    raise BrokerPolicyError(
                        READ_SCAN_LIMIT_MESSAGE, code="READ_OFFSET_SCAN_LIMIT"
                    )
                break
            next_offset = current_line
            next_column = current_column
            pending_current_line_remainder = line.stream_has_line_remainder
            break
        line_bytes = len(line.text.encode("utf-8"))
        content_lines.append(line.text)
        content_bytes += line_bytes
        end_line = current_line
        end_column = current_column + line.consumed_chars - 1
        if scan_limit_reached:
            break
        if not line.line_complete:
            next_offset = current_line
            next_column = current_column + line.consumed_chars
            pending_current_line_remainder = line.stream_has_line_remainder
            break
        if content_bytes >= max_bytes:
            next_offset = current_line + 1
            next_column = 1
            break
        if len(content_lines) >= limit:
            next_offset = current_line + 1
            next_column = 1
            break

    if not scan_limit_reached and (should_count_exact_total or saw_eof):
        remaining_lines = _count_remaining_text_lines(
            handle=handle,
            discard_current_line_remainder=pending_current_line_remainder,
        )
        exact_total_lines = current_line + remaining_lines
        total_lines: int | None = exact_total_lines
        if next_offset is not None and next_offset > exact_total_lines:
            next_offset = None
            next_column = None
    else:
        total_lines = None

    if (
        total_lines is not None
        and current_line < offset
        and not (current_line == 0 and offset == 1)
    ):
        raise BrokerPolicyError(
            f"Offset {offset} is out of range for this file ({total_lines} lines)",
            code=READ_OFFSET_OUT_OF_RANGE,
        )
    page_incomplete = next_offset is not None
    line_count_incomplete = total_lines is None
    truncated = scan_limit_reached or page_incomplete or line_count_incomplete
    truncation_reason = (
        "scan_budget"
        if scan_limit_reached
        else "line_count_budget"
        if line_count_incomplete
        else "page_limit"
        if page_incomplete
        else None
    )
    retry_hint = (
        READ_FILE_SCAN_LIMIT_RETRY_HINT
        if scan_limit_reached
        else READ_FILE_LINE_COUNT_BUDGET_RETRY_HINT
        if line_count_incomplete
        else READ_FILE_PAGE_LIMIT_RETRY_HINT
        if page_incomplete
        else None
    )
    return ReadLinesResult(
        content="".join(content_lines),
        column=column,
        total_lines=total_lines,
        end_line=end_line,
        end_column=end_column,
        next_offset=next_offset,
        next_column=next_column,
        truncated=truncated,
        truncation_reason=truncation_reason,
        retry_hint=retry_hint,
    )


def _count_remaining_text_lines(
    *,
    handle: TextIO,
    discard_current_line_remainder: bool,
) -> int:
    if discard_current_line_remainder:
        _discard_line_remainder(handle)

    remaining_count = 0
    while True:
        line = _read_bounded_text_line(
            handle,
            byte_budget=None,
            consume_remainder=True,
        )
        if line is None:
            return remaining_count
        remaining_count += 1


def _read_bounded_text_line(
    handle: TextIO,
    *,
    byte_budget: int | None,
    consume_remainder: bool,
    start_column: int = 1,
    scan_byte_budget: int | None = None,
) -> TextLineRead | None:
    skipped_bytes = _skip_line_columns(
        handle, start_column=start_column, scan_byte_budget=scan_byte_budget
    )
    remaining_scan_bytes = (
        None if scan_byte_budget is None else scan_byte_budget - skipped_bytes
    )
    read_size = _scan_read_size(remaining_scan_bytes)
    if remaining_scan_bytes is not None and byte_budget is not None:
        byte_budget = min(byte_budget, remaining_scan_bytes)
    chunk, chunk_bytes = _read_text_chunk(handle, read_size)
    if chunk == "":
        if start_column > 1:
            raise BrokerPolicyError(
                f"Column {start_column} is out of range for this line",
                code=READ_OFFSET_OUT_OF_RANGE,
            )
        return None

    body, newline = _split_line_newline(chunk)
    if newline and len(body) <= MAX_LINE_LENGTH:
        return _line_read_if_fits_byte_budget(
            text=chunk,
            byte_budget=byte_budget,
            scanned_bytes=skipped_bytes + chunk_bytes,
        )
    if not newline and len(chunk) < read_size:
        return _line_read_if_fits_byte_budget(
            text=chunk,
            byte_budget=byte_budget,
            scanned_bytes=skipped_bytes + chunk_bytes,
        )

    line = body[:MAX_LINE_LENGTH]
    pending_remainder = not newline
    if not _fits_byte_budget(
        text=line + newline,
        byte_budget=byte_budget,
    ):
        bounded_line = (
            _prefix_within_byte_budget(line, byte_budget=byte_budget)
            if byte_budget is not None
            else line
        )
        if bounded_line:
            return TextLineRead(
                text=bounded_line,
                fits_byte_budget=True,
                line_complete=False,
                stream_has_line_remainder=pending_remainder,
                scanned_bytes=skipped_bytes + chunk_bytes,
                consumed_chars=len(bounded_line),
            )
        return TextLineRead(
            text="",
            fits_byte_budget=False,
            line_complete=False,
            stream_has_line_remainder=pending_remainder,
            scanned_bytes=skipped_bytes + chunk_bytes,
            consumed_chars=0,
        )

    if pending_remainder and not consume_remainder:
        return TextLineRead(
            text=line,
            fits_byte_budget=True,
            line_complete=False,
            stream_has_line_remainder=True,
            scanned_bytes=skipped_bytes + chunk_bytes,
            consumed_chars=len(line),
        )

    suffix_newline = newline
    remainder_bytes = 0
    if not suffix_newline:
        suffix_newline, remainder_bytes = _discard_line_remainder(
            handle,
            scan_byte_budget=(
                None
                if remaining_scan_bytes is None
                else remaining_scan_bytes - chunk_bytes
            ),
        )
    return _line_read_if_fits_byte_budget(
        text=line + suffix_newline,
        byte_budget=byte_budget,
        line_complete=True,
        scanned_bytes=skipped_bytes + chunk_bytes + remainder_bytes,
    )


def _line_read_if_fits_byte_budget(
    *,
    text: str,
    byte_budget: int | None,
    line_complete: bool = True,
    scanned_bytes: int | None = None,
) -> TextLineRead:
    fits_byte_budget = _fits_byte_budget(text=text, byte_budget=byte_budget)
    if not fits_byte_budget and byte_budget is not None:
        body, _newline = _split_line_newline(text)
        bounded_body = _prefix_within_byte_budget(body, byte_budget=byte_budget)
        if bounded_body:
            return TextLineRead(
                text=bounded_body,
                fits_byte_budget=True,
                line_complete=False,
                stream_has_line_remainder=False,
                scanned_bytes=(
                    _encoded_len(text) if scanned_bytes is None else scanned_bytes
                ),
                consumed_chars=len(bounded_body),
            )
    return TextLineRead(
        text=text if fits_byte_budget else "",
        fits_byte_budget=fits_byte_budget,
        line_complete=line_complete,
        stream_has_line_remainder=False,
        scanned_bytes=(_encoded_len(text) if scanned_bytes is None else scanned_bytes),
        consumed_chars=len(text.removesuffix("\n")),
    )


def _prefix_within_byte_budget(text: str, *, byte_budget: int) -> str:
    if _encoded_len(text) <= byte_budget:
        return text
    low = 0
    high = len(text)
    while low < high:
        midpoint = (low + high + 1) // 2
        if _encoded_len(text[:midpoint]) <= byte_budget:
            low = midpoint
        else:
            high = midpoint - 1
    return text[:low]


def _scan_read_size(remaining_bytes: int | None) -> int:
    if remaining_bytes is None:
        return _LINE_READ_AHEAD_CHARS
    if remaining_bytes <= 0:
        raise BrokerPolicyError(READ_SCAN_LIMIT_MESSAGE, code="READ_OFFSET_SCAN_LIMIT")
    # TextIO sizes reads in characters; UTF-8 read-ahead is bounded to one chunk.
    return min(_LINE_READ_AHEAD_CHARS, remaining_bytes)


def _skip_line_columns(
    handle: TextIO, *, start_column: int, scan_byte_budget: int | None
) -> int:
    remaining = start_column - 1
    scanned_bytes = 0
    while remaining > 0:
        read_size = _scan_read_size(
            None if scan_byte_budget is None else scan_byte_budget - scanned_bytes
        )
        chunk, chunk_bytes = _read_text_chunk(handle, min(remaining, read_size))
        if chunk == "" or "\n" in chunk:
            raise BrokerPolicyError(
                f"Column {start_column} is out of range for this line",
                code=READ_OFFSET_OUT_OF_RANGE,
            )
        remaining -= len(chunk)
        scanned_bytes += chunk_bytes
    return scanned_bytes


def _fits_byte_budget(*, text: str, byte_budget: int | None) -> bool:
    if byte_budget is None:
        return True
    return _encoded_len(text) <= byte_budget


def _discard_line_remainder(
    handle: TextIO, *, scan_byte_budget: int | None = None
) -> tuple[str, int]:
    scanned_bytes = 0
    while True:
        chunk, chunk_bytes = _read_text_chunk(
            handle,
            _scan_read_size(
                None if scan_byte_budget is None else scan_byte_budget - scanned_bytes
            ),
        )
        if chunk == "":
            return "", scanned_bytes
        scanned_bytes += chunk_bytes
        _body, newline = _split_line_newline(chunk)
        if newline:
            return newline, scanned_bytes


def _read_text_chunk(handle: TextIO, size: int) -> tuple[str, int]:
    chunk = handle.readline(size)
    # Keep CRLF together when the character limit lands between its two bytes.
    if chunk.endswith("\r"):
        position = handle.tell()
        suffix = handle.read(1)
        if suffix == "\n":
            chunk += suffix
        elif suffix:
            handle.seek(position)
    scanned_bytes = _encoded_len(chunk)
    return chunk.replace("\r\n", "\n").replace("\r", "\n"), scanned_bytes


def _encoded_len(text: str) -> int:
    return len(text.encode("utf-8", errors="replace"))


def _split_line_newline(line: str) -> tuple[str, str]:
    if line.endswith("\n"):
        return line[:-1], "\n"
    return line, ""


__all__ = [
    "READ_FILE_PAGE_LIMIT_RETRY_HINT",
    "ReadLinesResult",
    "read_text_descriptor_lines",
    "read_text_value_lines",
]
