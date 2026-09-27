from __future__ import annotations

import errno
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from pantaray_agents.local_runtime.tooling.brokering import broker_direct_read_text
from pantaray_agents.local_runtime.tooling.brokering.broker_common import (
    BrokerPolicyError,
)
from pantaray_agents.local_runtime.tooling.brokering.broker_direct_read_text import (
    read_text_descriptor_lines,
    read_text_lines,
)


class _CountingLineStream:
    def __init__(self, text: str) -> None:
        self._text = text
        self._index = 0

    def __enter__(self) -> _CountingLineStream:
        return self

    def __exit__(self, exc_type: object, exc: object, tb: object) -> None:
        return None

    def readline(self, size: int = -1) -> str:
        if self._index >= len(self._text):
            return ""
        newline_index = self._text.find("\n", self._index)
        line_end = len(self._text) if newline_index < 0 else newline_index + 1
        if size >= 0:
            line_end = min(line_end, self._index + size)
        chunk = self._text[self._index : line_end]
        self._index = line_end
        return chunk

    @property
    def position(self) -> int:
        return self._index


def _patch_path_stream(
    monkeypatch: pytest.MonkeyPatch,
    *,
    stream: _CountingLineStream,
) -> None:
    monkeypatch.setattr(broker_direct_read_text.os, "open", lambda *args: 42)
    monkeypatch.setattr(
        broker_direct_read_text.os,
        "fstat",
        lambda _fd: SimpleNamespace(st_mode=stat.S_IFREG, st_size=0),
    )
    monkeypatch.setattr(
        broker_direct_read_text,
        "open",
        lambda *args, **kwargs: stream,
        raising=False,
    )
    monkeypatch.setattr(broker_direct_read_text.os, "close", lambda _fd: None)


def test_read_text_lines_reads_regular_file(tmp_path: Path) -> None:
    path = tmp_path / "regular.txt"
    path.write_text("first\nsecond\n", encoding="utf-8")

    result = read_text_lines(filepath=path, offset=1, limit=1)

    assert result.content == "first\n"
    assert result.total_lines == 2


def test_read_text_lines_rejects_symlink(tmp_path: Path) -> None:
    target = tmp_path / "target.txt"
    target.write_text("secret\n", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(target)

    with pytest.raises(OSError) as exc_info:
        read_text_lines(filepath=link, offset=1, limit=1)

    assert exc_info.value.errno == errno.ELOOP


def test_read_text_descriptor_lines_borrows_descriptor(tmp_path: Path) -> None:
    path = tmp_path / "borrowed.txt"
    path.write_text("first\nsecond\n", encoding="utf-8")
    descriptor = broker_direct_read_text.os.open(
        path, broker_direct_read_text.os.O_RDONLY
    )
    try:
        result = read_text_descriptor_lines(
            descriptor=descriptor,
            offset=1,
            limit=1,
        )

        assert result.content == "first\n"
        assert (
            broker_direct_read_text.os.fstat(descriptor).st_size == path.stat().st_size
        )
    finally:
        broker_direct_read_text.os.close(descriptor)


def test_read_text_descriptor_lines_rejects_non_regular_without_closing(
    tmp_path: Path,
) -> None:
    descriptor = broker_direct_read_text.os.open(
        tmp_path,
        broker_direct_read_text.os.O_RDONLY,
    )
    try:
        with pytest.raises(OSError) as exc_info:
            read_text_descriptor_lines(
                descriptor=descriptor,
                offset=1,
                limit=1,
            )

        assert exc_info.value.errno == errno.EINVAL
        broker_direct_read_text.os.fstat(descriptor)
    finally:
        broker_direct_read_text.os.close(descriptor)


def test_read_text_descriptor_lines_keeps_descriptor_after_decode_error(
    tmp_path: Path,
) -> None:
    path = tmp_path / "invalid.txt"
    path.write_bytes(b"\xff\n")
    descriptor = broker_direct_read_text.os.open(
        path, broker_direct_read_text.os.O_RDONLY
    )
    try:
        with pytest.raises(UnicodeDecodeError):
            read_text_descriptor_lines(
                descriptor=descriptor,
                offset=1,
                limit=1,
            )

        broker_direct_read_text.os.fstat(descriptor)
    finally:
        broker_direct_read_text.os.close(descriptor)


def test_read_text_lines_counts_total_lines_after_limit_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream("first\nsecond\nthird\n")
    _patch_path_stream(monkeypatch, stream=stream)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, limit=1)

    assert result.content == "first\n"
    assert result.end_line == 1
    assert result.total_lines == 3
    assert result.next_offset == 2
    assert result.truncated is True
    assert result.truncation_reason == "page_limit"
    assert result.next_column == 1
    assert result.retry_hint == (
        "Continue with offset=next_offset and column=next_column."
    )
    assert stream.position == len("first\nsecond\nthird\n")


def test_read_text_lines_counts_total_lines_after_byte_cap_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream("abc\nde\nthird\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_BYTES", 5)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, limit=2_000)

    assert result.content == "abc\nd"
    assert result.end_line == 2
    assert result.end_column == 1
    assert result.total_lines == 3
    assert result.next_offset == 2
    assert result.next_column == 2
    assert result.truncated is True
    assert result.truncation_reason == "page_limit"
    assert stream.position == len("abc\nde\nthird\n")


def test_read_text_lines_counts_total_after_long_line_exceeds_byte_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream("fit\n" + ("a" * 10_000) + "\nnext\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_BYTES", 20)
    monkeypatch.setattr(broker_direct_read_text, "MAX_LINE_LENGTH", 8)
    monkeypatch.setattr(broker_direct_read_text, "_LINE_READ_AHEAD_CHARS", 9)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, limit=2_000)

    assert result.content == "fit\n" + ("a" * 8)
    assert result.end_line == 2
    assert result.end_column == 8
    assert result.total_lines == 3
    assert result.next_offset == 2
    assert result.next_column == 9
    assert result.truncated is True
    assert result.truncation_reason == "page_limit"
    assert stream.position == len("fit\n" + ("a" * 10_000) + "\nnext\n")


def test_read_text_lines_stops_after_long_line_clamp(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream(("a" * 10_000) + "\nnext\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_LINE_LENGTH", 8)
    monkeypatch.setattr(broker_direct_read_text, "_LINE_READ_AHEAD_CHARS", 9)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, limit=1)

    assert result.content == "a" * 8
    assert result.end_line == 1
    assert result.end_column == 8
    assert result.total_lines == 2
    assert result.next_offset == 1
    assert result.next_column == 9
    assert result.truncated is True
    assert result.truncation_reason == "page_limit"
    assert stream.position == len(("a" * 10_000) + "\nnext\n")


def test_read_text_lines_consumes_skipped_long_lines_to_reach_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream(("a" * 10_000) + "\nnext\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_LINE_LENGTH", 8)
    monkeypatch.setattr(broker_direct_read_text, "_LINE_READ_AHEAD_CHARS", 9)

    result = read_text_lines(filepath=Path("unused.txt"), offset=2, limit=1)

    assert result.content == "next\n"
    assert result.end_line == 2
    assert result.total_lines == 2
    assert result.next_offset is None
    assert result.truncated is False


def test_read_text_lines_continues_long_line_from_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream(("abcdefghij" * 2) + "\nnext\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_LINE_LENGTH", 8)
    monkeypatch.setattr(broker_direct_read_text, "_LINE_READ_AHEAD_CHARS", 9)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, column=9, limit=1)

    assert result.content == "ijabcdef"
    assert result.end_line == 1
    assert result.end_column == 16
    assert result.next_offset == 1
    assert result.next_column == 17
    assert result.total_lines == 2


def test_read_text_lines_pages_multibyte_line_without_stalling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stream = _CountingLineStream("あ" * 10 + "\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_BYTES", 10)

    result = read_text_lines(filepath=Path("unused.txt"), offset=1, limit=1)

    assert result.content == "あ" * 3
    assert result.next_offset == 1
    assert result.next_column == 4


@pytest.mark.parametrize("offset", [4, 5])
def test_unreachable_start_returns_retryable_error_including_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    offset: int,
) -> None:
    path = tmp_path / "bounded.txt"
    path.write_text("".join(f"{n:03}\n" for n in range(1, 8)))
    monkeypatch.setattr(broker_direct_read_text, "MAX_TEXT_SCAN_BYTES", 12)
    monkeypatch.setattr(broker_direct_read_text, "MAX_TOTAL_LINE_COUNT_BYTES", 12)
    with pytest.raises(BrokerPolicyError) as raised:
        read_text_lines(filepath=path, offset=offset, limit=2)
    assert raised.value.code == "READ_OFFSET_SCAN_LIMIT"
    assert "smaller offset or column" in str(raised.value)
    retry = read_text_lines(filepath=path, offset=3, limit=2)
    assert retry.content == "003\n"
    assert retry.end_line == 3
    assert retry.truncated is True
    assert retry.next_offset is None
    assert retry.next_column is None
    assert retry.truncation_reason == "scan_budget"
    assert "scan limit" in retry.retry_hint


def test_multimegabyte_file_tail_is_readable_without_splitting(tmp_path: Path) -> None:
    path = tmp_path / "large.txt"
    path.write_text(("かな" * 100 + "\n") * 5_000 + "LAST MARKER", encoding="utf-8")
    result = read_text_lines(filepath=path, offset=5_001, limit=2)
    assert result.content == "LAST MARKER"
    assert result.total_lines == 5_001
    assert result.next_offset is None


@pytest.mark.parametrize("position", [{"offset": 2}, {"offset": 1, "column": 500_000}])
def test_scan_stops_inside_a_long_line(
    monkeypatch: pytest.MonkeyPatch,
    position: dict[str, int],
) -> None:
    stream = _CountingLineStream("x" * 1_000_000 + "\nnext\n")
    _patch_path_stream(monkeypatch, stream=stream)
    monkeypatch.setattr(broker_direct_read_text, "MAX_TEXT_SCAN_BYTES", 4_096)
    with pytest.raises(BrokerPolicyError) as raised:
        read_text_lines(filepath=Path("unused.txt"), limit=1, **position)
    assert raised.value.code == "READ_OFFSET_SCAN_LIMIT"
    assert stream.position <= 4_096


@pytest.mark.parametrize(
    ("tail", "budget", "expected"),
    [("abcdefgh\n", 7, "abc"), ("あいうえお\n", 11, "あい")],
)
def test_scan_limit_returns_available_partial_line(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    tail: str,
    budget: int,
    expected: str,
) -> None:
    path = tmp_path / "partial.txt"
    path.write_text("one\n" + tail, encoding="utf-8")
    monkeypatch.setattr(broker_direct_read_text, "MAX_TEXT_SCAN_BYTES", budget)
    result = read_text_lines(filepath=path, offset=1, limit=10)
    assert result.content == "one\n" + expected
    assert result.end_line == 2
    assert result.end_column == len(expected)
    assert result.truncated is True
    assert result.next_offset is None
    assert result.next_column is None
    assert result.truncation_reason == "scan_budget"
    assert "scan limit" in result.retry_hint


@pytest.mark.parametrize("newline", ["\r\n", "\r"])
def test_scan_budget_counts_original_newline_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    newline: str,
) -> None:
    path = tmp_path / "newlines.txt"
    path.write_bytes((newline * 10).encode("utf-8"))
    monkeypatch.setattr(broker_direct_read_text, "MAX_TEXT_SCAN_BYTES", 4)
    with pytest.raises(BrokerPolicyError) as raised:
        read_text_lines(filepath=path, offset=4 // len(newline) + 1, limit=1)
    assert raised.value.code == "READ_OFFSET_SCAN_LIMIT"


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_newline_at_chunk_boundary_preserves_lines_and_columns(
    tmp_path: Path,
    newline: str,
) -> None:
    path = tmp_path / "boundary.txt"
    line = "x" * broker_direct_read_text.MAX_LINE_LENGTH
    path.write_bytes((line + newline + "tail" + newline).encode("utf-8"))
    result = read_text_lines(filepath=path, offset=1, limit=2)
    assert result.content == line + "\ntail\n"
    assert result.total_lines == 2
    assert result.end_line == 2
    assert result.end_column == 4
    assert result.next_offset is None
