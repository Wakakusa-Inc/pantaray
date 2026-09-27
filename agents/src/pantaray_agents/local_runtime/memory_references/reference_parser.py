from __future__ import annotations

import re
from dataclasses import dataclass

REFERENCE_PATTERN = re.compile(
    r"\[\[ref:(?P<local_ref_id>[A-Za-z0-9_]+)"
    r'(?:\s+note:"(?P<note>(?:[^"\\]|\\.)*)")?'
    r"\]\]"
)
WHITESPACE_PATTERN = re.compile(r"[ \t]{2,}")


@dataclass(frozen=True, slots=True)
class MarkdownReferenceOccurrence:
    local_ref_id: str
    note: str | None
    anchor_text: str
    anchor_order: int
    match_start: int
    match_end: int
    id_start: int
    id_end: int


def has_reference_markup(markdown: str) -> bool:
    return bool(REFERENCE_PATTERN.search(markdown or ""))


def extract_markdown_references(
    markdown: str,
) -> tuple[MarkdownReferenceOccurrence, ...]:
    text = markdown or ""
    occurrences: list[MarkdownReferenceOccurrence] = []
    for anchor_order, match in enumerate(REFERENCE_PATTERN.finditer(text)):
        line_start = text.rfind("\n", 0, match.start()) + 1
        line_end = text.find("\n", match.end())
        if line_end == -1:
            line_end = len(text)
        line_text = text[line_start:line_end]
        anchor_text = _normalize_anchor_text(
            REFERENCE_PATTERN.sub("", line_text).strip()
        )
        occurrences.append(
            MarkdownReferenceOccurrence(
                local_ref_id=match.group("local_ref_id"),
                note=_unescape_note(match.group("note")),
                anchor_text=anchor_text,
                anchor_order=anchor_order,
                match_start=match.start(),
                match_end=match.end(),
                id_start=match.start("local_ref_id"),
                id_end=match.end("local_ref_id"),
            )
        )
    return tuple(occurrences)


def replace_reference_occurrences(
    markdown: str,
    replacements_by_anchor_order: dict[int, str],
) -> str:
    if not replacements_by_anchor_order:
        return markdown
    text = markdown or ""
    chunks: list[str] = []
    cursor = 0
    for occurrence in extract_markdown_references(text):
        replacement = replacements_by_anchor_order.get(occurrence.anchor_order)
        if replacement is None or replacement == occurrence.local_ref_id:
            continue
        chunks.append(text[cursor : occurrence.id_start])
        chunks.append(replacement)
        cursor = occurrence.id_end
    chunks.append(text[cursor:])
    return "".join(chunks)


def replace_reference_ids(markdown: str, replacements: dict[str, str]) -> str:
    if not replacements:
        return markdown
    occurrence_replacements = {
        occurrence.anchor_order: replacement
        for occurrence in extract_markdown_references(markdown or "")
        if (replacement := replacements.get(occurrence.local_ref_id)) is not None
    }
    return replace_reference_occurrences(markdown, occurrence_replacements)


def remove_reference_occurrences(markdown: str, anchor_orders: set[int]) -> str:
    if not anchor_orders:
        return markdown
    text = markdown or ""
    chunks: list[str] = []
    cursor = 0
    for occurrence in extract_markdown_references(text):
        if occurrence.anchor_order not in anchor_orders:
            continue
        removal_start = _reference_removal_start(text, occurrence)
        chunks.append(text[cursor:removal_start])
        cursor = occurrence.match_end
    chunks.append(text[cursor:])
    return "".join(chunks)


def remove_reference_ids(markdown: str, local_ref_ids: set[str]) -> str:
    if not local_ref_ids:
        return markdown
    anchor_orders = {
        occurrence.anchor_order
        for occurrence in extract_markdown_references(markdown or "")
        if occurrence.local_ref_id in local_ref_ids
    }
    return remove_reference_occurrences(markdown, anchor_orders)


def _normalize_anchor_text(text: str) -> str:
    normalized = WHITESPACE_PATTERN.sub(" ", text).strip()
    return normalized


def _reference_removal_start(
    text: str,
    occurrence: MarkdownReferenceOccurrence,
) -> int:
    following = text[occurrence.match_end : occurrence.match_end + 1]
    if following not in {"", "\n", "\r"}:
        return occurrence.match_start
    line_start = text.rfind("\n", 0, occurrence.match_start) + 1
    return len(text[line_start : occurrence.match_start].rstrip(" \t")) + line_start


def _unescape_note(raw_note: str | None) -> str | None:
    if raw_note is None:
        return None
    return raw_note.replace(r"\\", "\\").replace(r"\"", '"')
