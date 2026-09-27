"""Small unified-diff scanner shared by patch application boundaries."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass

HUNK_HEADER_RE = re.compile(
    r"^@@ -\d+(?:,(?P<old_count>\d+))? \+\d+(?:,(?P<new_count>\d+))? @@"
)
DEFAULT_HUNK_LINE_COUNT = 1


@dataclass(frozen=True, slots=True)
class UnifiedDiffHeaderPair:
    old_header: str
    new_header: str
    first_line_index: int
    next_header_index: int


def scan_unified_diff_header_pairs(
    lines: Sequence[str],
) -> tuple[UnifiedDiffHeaderPair, ...]:
    """Return file header pairs while ignoring ---/+++ lines inside hunks."""
    pairs: list[UnifiedDiffHeaderPair] = []
    index = 0
    while index < len(lines) - 1:
        if _is_file_header_at(lines, index):
            first_line_index = index
            index += 2
            while index < len(lines):
                if _is_file_header_at(lines, index):
                    break
                if lines[index].startswith("@@ "):
                    index = _consume_hunk(lines, index)
                    continue
                index += 1
            pairs.append(
                UnifiedDiffHeaderPair(
                    old_header=lines[first_line_index][4:],
                    new_header=lines[first_line_index + 1][4:],
                    first_line_index=first_line_index,
                    next_header_index=index,
                )
            )
            continue
        index += 1
    return tuple(pairs)


def _is_file_header_at(lines: Sequence[str], index: int) -> bool:
    return (
        index + 1 < len(lines)
        and lines[index].startswith("--- ")
        and lines[index + 1].startswith("+++ ")
    )


def _consume_hunk(lines: Sequence[str], hunk_header_index: int) -> int:
    match = HUNK_HEADER_RE.match(lines[hunk_header_index])
    if match is None:
        return hunk_header_index + 1
    expected_old = _parse_hunk_line_count(match.group("old_count"))
    expected_new = _parse_hunk_line_count(match.group("new_count"))
    seen_old = 0
    seen_new = 0
    index = hunk_header_index + 1
    while index < len(lines) and (seen_old < expected_old or seen_new < expected_new):
        line = lines[index]
        if line.startswith(" "):
            seen_old += 1
            seen_new += 1
        elif line.startswith("-"):
            seen_old += 1
        elif line.startswith("+"):
            seen_new += 1
        elif line.startswith("\\"):
            pass
        else:
            break
        index += 1
    return index


def _parse_hunk_line_count(raw_count: str | None) -> int:
    if raw_count is None:
        return DEFAULT_HUNK_LINE_COUNT
    return int(raw_count)
