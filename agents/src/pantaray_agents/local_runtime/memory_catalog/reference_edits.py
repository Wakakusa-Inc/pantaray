from __future__ import annotations

import re
from collections import Counter

from pantaray_agents.local_runtime.memory_references.reference_parser import (
    REFERENCE_PATTERN,
    extract_markdown_references,
    remove_reference_occurrences,
)

from .errors import MemoryLinkValidationError
from .fragments import normalize_markdown, parse_document
from .models import MemoryDocument

REFERENCE_START_PATTERN = re.compile(r"(?<!\\)\[\[ref:")
_CONTROL_CHAR_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_LINKABLE_SOURCE_KINDS = frozenset(("paragraph", "list_item"))


def insert_memory_reference(
    *,
    documents: tuple[MemoryDocument, ...],
    source_path: str,
    exact_text: str,
    occurrence: int,
    local_ref_id: str,
    note: str,
) -> tuple[tuple[MemoryDocument, ...], str]:
    """Insert a host-issued ref at an exact block; leave other files untouched."""
    validate_reference_note(note)
    if occurrence < 1:
        raise MemoryLinkValidationError("anchor occurrence must be >= 1")
    # Parser offsets refer to normalized text, including for externally edited files.
    normalized = tuple(
        MemoryDocument(item.source_path, normalize_markdown(item.content))
        if item.source_path == source_path
        else item
        for item in documents
    )
    index, offset, anchor_text = _resolve_anchor(
        documents=normalized,
        source_path=source_path,
        exact_text=exact_text,
        occurrence=occurrence,
    )
    document = normalized[index]
    content = (
        document.content[:offset].rstrip(" \t") + " " + _render_tag(local_ref_id, note)
    )
    content += document.content[offset:]
    updated = list(normalized)
    updated[index] = MemoryDocument(document.source_path, content)
    return tuple(updated), anchor_text


def _resolve_anchor(
    *,
    documents: tuple[MemoryDocument, ...],
    source_path: str,
    exact_text: str,
    occurrence: int,
) -> tuple[int, int, str]:
    candidates: list[tuple[int, int, str]] = []
    expected = exact_text.strip()
    for document_index, document in enumerate(documents):
        if document.source_path != source_path:
            continue
        for block in parse_document(document.source_path, document.content):
            if block.block_kind not in _LINKABLE_SOURCE_KINDS:
                continue
            raw = document.content[block.start_offset : block.end_offset].strip()
            occurrences = extract_markdown_references(raw)
            without_refs = remove_reference_occurrences(
                raw,
                {item.anchor_order for item in occurrences},
            ).strip()
            if expected in {block.content_text.strip(), raw, without_refs}:
                end = block.end_offset
                while end > block.start_offset and document.content[end - 1] in "\r\n":
                    end -= 1
                candidates.append((document_index, end, without_refs))
    if len(candidates) < occurrence:
        raise MemoryLinkValidationError(
            "anchor did not resolve to the requested occurrence"
        )
    return candidates[occurrence - 1]


def _render_tag(local_ref_id: str, note: str) -> str:
    escaped = note.replace("\\", "\\\\").replace('"', '\\"')
    return f'[[ref:{local_ref_id} note:"{escaped}"]]'


def validate_reference_note(note: str) -> None:
    if (
        not note.strip()
        or "\n" in note
        or "\r" in note
        or _CONTROL_CHAR_RE.search(note)
    ):
        raise MemoryLinkValidationError(
            "reference note must be nonblank single-line text"
        )


def validate_reference_text_replacement(*, path: str, before: str, after: str) -> None:
    """A model may preserve or remove tags, but only the host can create them."""
    old = Counter(
        (ref.local_ref_id, ref.note) for ref in extract_markdown_references(before)
    )
    new = Counter(
        (ref.local_ref_id, ref.note) for ref in extract_markdown_references(after)
    )
    if _unparsed_reference_lines(after) - _unparsed_reference_lines(before):
        raise MemoryLinkValidationError(
            "new reference markup must be complete and host-issued"
        )
    if new - old:
        raise MemoryLinkValidationError("use link_memory to add or change references")
    validate_removed_reference_markup(
        before=(MemoryDocument(path, before),),
        after=(MemoryDocument(path, after),),
        removed_ids={ref_id for ref_id, _ in old} - {ref_id for ref_id, _ in new},
    )


def _unparsed_reference_lines(text: str) -> Counter[str]:
    return Counter(
        line.strip()
        for line in REFERENCE_PATTERN.sub("", text).splitlines()
        if REFERENCE_START_PATTERN.search(line)
    )


def validate_removed_reference_markup(
    *,
    before: tuple[MemoryDocument, ...],
    after: tuple[MemoryDocument, ...],
    removed_ids: set[str],
) -> None:
    if removed_ids:
        mentions = _unparsed_ref_mentions(after, removed_ids)
        if mentions and mentions - _unparsed_ref_mentions(
            before, {ref_id for ref_id, _, _ in mentions}
        ):
            raise MemoryLinkValidationError(
                "a deleted ref ID remains outside a complete tag; remove its complete markup"
            )


def _unparsed_ref_mentions(
    documents: tuple[MemoryDocument, ...],
    ref_ids: set[str],
) -> Counter[tuple[str, str, str]]:
    # Preserve existing literal lines even when moved or indented. A deleted
    # literal elsewhere must not hide an ID stranded in a different context.
    mentions: Counter[tuple[str, str, str]] = Counter()
    # Design limit: one scan per removed ID; revisit if 10,000-ref deletion exceeds 1 s.
    for document in documents:
        content = REFERENCE_PATTERN.sub("", document.content)
        for ref_id in ref_ids:
            offset = content.find(ref_id)
            while offset != -1:
                start = content.rfind("\n", 0, offset) + 1
                end = content.find("\n", offset)
                if end == -1:
                    end = len(content)
                context = " ".join(content[start:end].split())
                mentions[ref_id, document.source_path, context] += content.count(
                    ref_id, offset, end
                )
                offset = content.find(ref_id, end)
    return mentions
