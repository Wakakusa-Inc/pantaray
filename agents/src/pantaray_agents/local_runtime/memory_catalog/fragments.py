from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from pantaray_agents.local_runtime.memory_references.reference_parser import (
    extract_markdown_references,
)

from .models import MemoryBlockKind, MemoryDocument, MemoryFragment

MEMORY_FRAGMENT_SCHEMA_VERSION = 1
INLINE_MEMORY_PATH = "body.md"
RECORD_ROOT_PATH = "@record"

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+?)\s*$")
_BLOCK_QUOTE_RE = re.compile(r"^\s*>\s?(.*?)\s*$")
_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-+:?\s*\|)+\s*:?-+:?\s*\|?\s*$")


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    source_path: str
    block_kind: MemoryBlockKind
    block_index: int
    heading_path: str | None
    content_text: str
    start_offset: int
    end_offset: int


def normalize_markdown(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def content_sha256(text: str) -> str:
    return hashlib.sha256(normalize_markdown(text).encode("utf-8")).hexdigest()


def artifact_content_sha256(documents: tuple[MemoryDocument, ...]) -> str:
    digest = hashlib.sha256()
    for document in sorted(documents, key=lambda item: item.source_path):
        digest.update(document.source_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(normalize_markdown(document.content).encode("utf-8"))
        digest.update(b"\0")
    return digest.hexdigest()


def parse_document(source_path: str, text: str) -> tuple[ParsedBlock, ...]:
    normalized = normalize_markdown(text)
    blocks: list[ParsedBlock] = [
        ParsedBlock(
            source_path, "document_root", 0, None, normalized, 0, len(normalized)
        )
    ]
    heading_stack: list[tuple[int, str]] = []
    lines = normalized.splitlines(keepends=True)
    offset = 0
    block_index = 1
    paragraph_start: int | None = None
    paragraph_lines: list[str] = []
    code_start: int | None = None
    code_lines: list[str] = []
    table_start: int | None = None
    table_lines: list[str] = []

    def heading_path() -> str | None:
        return " / ".join(item[1] for item in heading_stack) or None

    def append(kind: MemoryBlockKind, content: str, start: int, end: int) -> None:
        nonlocal block_index
        blocks.append(
            ParsedBlock(
                source_path,
                kind,
                block_index,
                heading_path(),
                content,
                start,
                end,
            )
        )
        block_index += 1

    def flush_paragraph(end: int) -> None:
        nonlocal paragraph_start
        if paragraph_start is not None:
            append("paragraph", " ".join(paragraph_lines).strip(), paragraph_start, end)
        paragraph_start = None
        paragraph_lines.clear()

    def flush_table(end: int) -> None:
        nonlocal table_start
        if table_start is not None:
            append("table", "\n".join(table_lines).strip(), table_start, end)
        table_start = None
        table_lines.clear()

    for line_index, line in enumerate(lines):
        raw = line.removesuffix("\n")
        line_end = offset + len(line)
        if code_start is not None:
            code_lines.append(raw)
            if raw.strip().startswith("```") and len(code_lines) > 1:
                append("code_block", "\n".join(code_lines), code_start, line_end)
                code_start = None
                code_lines.clear()
            offset = line_end
            continue
        if raw.strip().startswith("```"):
            flush_paragraph(offset)
            flush_table(offset)
            code_start = offset
            code_lines.append(raw)
            offset = line_end
            continue
        if "|" in raw and raw.strip():
            is_separator = bool(_TABLE_SEPARATOR_RE.match(raw))
            next_raw = (
                lines[line_index + 1].removesuffix("\n")
                if line_index + 1 < len(lines)
                else ""
            )
            is_header = bool(_TABLE_SEPARATOR_RE.match(next_raw))
            if table_start is not None or is_separator or is_header:
                flush_paragraph(offset)
                if table_start is None:
                    table_start = offset
                table_lines.append(raw)
                offset = line_end
                continue
        elif table_start is not None:
            flush_table(offset)
        heading = _HEADING_RE.match(raw)
        list_item = _LIST_ITEM_RE.match(raw)
        block_quote = _BLOCK_QUOTE_RE.match(raw)
        if heading or list_item or block_quote or not raw.strip():
            flush_paragraph(offset)
        if heading:
            level = len(heading.group(1))
            label = heading.group(2).strip()
            heading_stack = [item for item in heading_stack if item[0] < level]
            heading_stack.append((level, label))
            append("heading", label, offset, line_end)
        elif list_item:
            append("list_item", list_item.group(1).strip(), offset, line_end)
        elif block_quote:
            append("block_quote", block_quote.group(1).strip(), offset, line_end)
        elif raw.strip():
            if paragraph_start is None:
                paragraph_start = offset
            paragraph_lines.append(raw.strip())
        offset = line_end
    flush_paragraph(offset)
    flush_table(offset)
    if code_start is not None:
        append("other", "\n".join(code_lines), code_start, offset)
    return tuple(blocks)


@dataclass(frozen=True, slots=True)
class LocatedMemoryReference:
    local_ref_id: str
    source_path: str
    block_index: int | None
    reference_note: str | None


def locate_memory_references(
    documents: tuple[MemoryDocument, ...],
) -> tuple[LocatedMemoryReference, ...]:
    located: list[LocatedMemoryReference] = []
    for document in documents:
        content = normalize_markdown(document.content)
        blocks = iter(parse_document(document.source_path, content)[1:])
        block = next(blocks, None)
        for occurrence in extract_markdown_references(content):
            while block is not None and block.end_offset <= occurrence.match_start:
                block = next(blocks, None)
            containing = (
                block
                if block is not None
                and block.start_offset <= occurrence.match_start
                and occurrence.match_end <= block.end_offset
                else None
            )
            located.append(
                LocatedMemoryReference(
                    occurrence.local_ref_id,
                    document.source_path,
                    None if containing is None else containing.block_index,
                    occurrence.note,
                )
            )
    return tuple(located)


def build_fragments(
    *,
    user_id: str,
    revision_id: str,
    documents: tuple[MemoryDocument, ...],
    include_record_root: bool = False,
) -> tuple[MemoryFragment, ...]:
    fragments: list[MemoryFragment] = []
    if include_record_root:
        record_text = "\n\n".join(
            f"<!-- {item.source_path} -->\n{normalize_markdown(item.content)}"
            for item in sorted(documents, key=lambda item: item.source_path)
        )
        fragments.append(
            _fragment(
                user_id=user_id,
                revision_id=revision_id,
                source_path=RECORD_ROOT_PATH,
                kind="record_root",
                index=0,
                heading_path=None,
                content=record_text,
            )
        )
    for document in sorted(documents, key=lambda item: item.source_path):
        for block in parse_document(document.source_path, document.content):
            fragments.append(
                _fragment(
                    user_id=user_id,
                    revision_id=revision_id,
                    source_path=block.source_path,
                    kind=block.block_kind,
                    index=block.block_index,
                    heading_path=block.heading_path,
                    content=block.content_text,
                )
            )
    return tuple(fragments)


def _fragment(
    *,
    user_id: str,
    revision_id: str,
    source_path: str,
    kind: MemoryBlockKind,
    index: int,
    heading_path: str | None,
    content: str,
) -> MemoryFragment:
    normalized = normalize_markdown(content)
    digest = content_sha256(normalized)
    identity = "\0".join((revision_id, source_path, str(index), digest))
    fragment_id = f"frag_{hashlib.sha256(identity.encode('utf-8')).hexdigest()[:32]}"
    return MemoryFragment(
        user_id=user_id,
        fragment_id=fragment_id,
        revision_id=revision_id,
        source_path=source_path,
        block_kind=kind,
        block_index=index,
        heading_path=heading_path,
        content_text=normalized,
        content_sha256=digest,
    )
