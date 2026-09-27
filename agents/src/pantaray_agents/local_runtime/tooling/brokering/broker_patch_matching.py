from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

LINE_OMISSION_MARKER = "<OMITTED>"
MAX_CONTEXT_GAP_LINES = 80
MAX_EDIT_SPAN_LINES = 160


class PatchMatchFailureReason(StrEnum):
    CONTEXT_NOT_FOUND = "context_not_found"
    CONTEXT_AMBIGUOUS = "context_ambiguous"
    EDIT_ORDER_INVALID = "edit_order_invalid"
    LINE_PATTERN_INVALID = "line_pattern_invalid"


class PatchMatchFailure(RuntimeError):
    def __init__(self, message: str, *, reason: PatchMatchFailureReason) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class PatchEditMatch:
    old_start: int
    old_end: int


@dataclass(frozen=True, slots=True)
class PatchEditLocation:
    old_start: int
    old_end: int
    visible_start: int
    visible_end: int


@dataclass(frozen=True, slots=True)
class _PatternSpan:
    start: int
    end: int


def find_patch_edit_match(
    *,
    current_lines: list[str],
    before_lines: list[str],
    old_lines: list[str],
    after_lines: list[str],
    cursor: int,
) -> PatchEditMatch:
    location = find_patch_edit_location(
        current_lines=current_lines,
        before_lines=before_lines,
        old_lines=old_lines,
        after_lines=after_lines,
        cursor=cursor,
    )
    return PatchEditMatch(old_start=location.old_start, old_end=location.old_end)


def find_patch_edit_location(
    *,
    current_lines: list[str],
    before_lines: list[str],
    old_lines: list[str],
    after_lines: list[str],
    cursor: int,
) -> PatchEditLocation:
    _validate_line_patterns(before_lines + old_lines + after_lines)
    old_matches = _find_old_line_matches(
        current_lines=current_lines,
        old_lines=old_lines,
    )
    if not old_matches:
        raise PatchMatchFailure(
            "old_lines did not match the current file content.",
            reason=PatchMatchFailureReason.CONTEXT_NOT_FOUND,
        )
    indexed_matches_after_cursor = [
        (index, match)
        for index, match in enumerate(old_matches)
        if match.old_start >= cursor
    ]
    if not indexed_matches_after_cursor:
        raise PatchMatchFailure(
            "old_lines matched only before the previous edit.",
            reason=PatchMatchFailureReason.EDIT_ORDER_INVALID,
        )

    hinted_locations: list[PatchEditLocation] = []
    for index, match in indexed_matches_after_cursor:
        visible_start = _before_hint_visible_start(
            current_lines=current_lines,
            before_lines=before_lines,
            old_start=match.old_start,
            previous_old_end=_previous_old_end(old_matches, index),
        )
        if visible_start is None:
            continue
        visible_end = _after_hint_visible_end(
            current_lines=current_lines,
            after_lines=after_lines,
            old_end=match.old_end,
            next_old_start=_next_old_start(old_matches, index),
        )
        if visible_end is None:
            continue
        hinted_locations.append(
            PatchEditLocation(
                old_start=match.old_start,
                old_end=match.old_end,
                visible_start=visible_start,
                visible_end=visible_end,
            )
        )
    if not hinted_locations:
        raise PatchMatchFailure(
            "old_lines matched, but before_lines/after_lines did not match nearby.",
            reason=PatchMatchFailureReason.CONTEXT_NOT_FOUND,
        )
    if len(hinted_locations) > 1:
        raise PatchMatchFailure(
            "old_lines matched multiple locations.",
            reason=PatchMatchFailureReason.CONTEXT_AMBIGUOUS,
        )
    return hinted_locations[0]


def _validate_line_patterns(lines: list[str]) -> None:
    for line in lines:
        marker_count = line.count(LINE_OMISSION_MARKER)
        if marker_count == 0:
            continue
        if marker_count > 1:
            raise PatchMatchFailure(
                f"{LINE_OMISSION_MARKER} may appear at most once per existing line.",
                reason=PatchMatchFailureReason.LINE_PATTERN_INVALID,
            )
        prefix, suffix = line.split(LINE_OMISSION_MARKER)
        if not prefix or not suffix:
            raise PatchMatchFailure(
                f"{LINE_OMISSION_MARKER} requires non-empty prefix and suffix.",
                reason=PatchMatchFailureReason.LINE_PATTERN_INVALID,
            )


def _find_old_line_matches(
    *,
    current_lines: list[str],
    old_lines: list[str],
) -> list[PatchEditMatch]:
    matches: list[PatchEditMatch] = []
    last_start = len(current_lines) - len(old_lines)
    for start in range(last_start + 1):
        end = start + len(old_lines)
        if _line_patterns_match(
            current_lines=current_lines[start:end],
            patterns=old_lines,
        ):
            matches.append(PatchEditMatch(old_start=start, old_end=end))
    return matches


def _before_hint_visible_start(
    *,
    current_lines: list[str],
    before_lines: list[str],
    old_start: int,
    previous_old_end: int | None,
) -> int | None:
    if not before_lines:
        return old_start
    search_start = max(0, old_start - MAX_EDIT_SPAN_LINES)
    if previous_old_end is not None:
        search_start = max(search_start, previous_old_end)
    span = _ordered_pattern_span_in_range(
        current_lines=current_lines,
        patterns=before_lines,
        start=search_start,
        stop=old_start,
    )
    return span.start if span is not None else None


def _after_hint_visible_end(
    *,
    current_lines: list[str],
    after_lines: list[str],
    old_end: int,
    next_old_start: int | None,
) -> int | None:
    if not after_lines:
        return old_end
    search_stop = min(len(current_lines), old_end + MAX_EDIT_SPAN_LINES)
    if next_old_start is not None:
        search_stop = min(search_stop, next_old_start)
    span = _ordered_pattern_span_in_range(
        current_lines=current_lines,
        patterns=after_lines,
        start=old_end,
        stop=search_stop,
    )
    return span.end if span is not None else None


def _ordered_pattern_span_in_range(
    *,
    current_lines: list[str],
    patterns: list[str],
    start: int,
    stop: int,
) -> _PatternSpan | None:
    cursor = start
    previous_match = start - 1
    first_match: int | None = None
    for pattern in patterns:
        next_match = _find_next_pattern_match(
            current_lines=current_lines,
            pattern=pattern,
            start=cursor,
            stop=stop,
        )
        if next_match is None:
            return None
        if (
            previous_match >= start
            and next_match - previous_match > MAX_CONTEXT_GAP_LINES
        ):
            return None
        if first_match is None:
            first_match = next_match
        previous_match = next_match
        cursor = next_match + 1
    if first_match is None:
        return _PatternSpan(start=start, end=start)
    return _PatternSpan(start=first_match, end=previous_match + 1)


def _find_next_pattern_match(
    *,
    current_lines: list[str],
    pattern: str,
    start: int,
    stop: int,
) -> int | None:
    for index in range(start, stop):
        if _line_matches_pattern(current_lines[index], pattern):
            return index
    return None


def _previous_old_end(
    matches: list[PatchEditMatch],
    index: int,
) -> int | None:
    if index == 0:
        return None
    return matches[index - 1].old_end


def _next_old_start(
    matches: list[PatchEditMatch],
    index: int,
) -> int | None:
    if index == len(matches) - 1:
        return None
    return matches[index + 1].old_start


def _line_patterns_match(
    *,
    current_lines: list[str],
    patterns: list[str],
) -> bool:
    if len(current_lines) != len(patterns):
        return False
    return all(
        _line_matches_pattern(current_line, pattern)
        for current_line, pattern in zip(current_lines, patterns, strict=True)
    )


def _line_matches_pattern(current_line: str, pattern: str) -> bool:
    if LINE_OMISSION_MARKER not in pattern:
        return current_line == pattern
    prefix, suffix = pattern.split(LINE_OMISSION_MARKER)
    if len(current_line) < len(prefix) + len(suffix):
        return False
    return current_line.startswith(prefix) and current_line.endswith(suffix)
