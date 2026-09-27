from __future__ import annotations

from .models import MemoryDocument

TODO_DOCUMENT_PATH = "insights/todos.md"


def render_artifact_documents(documents: tuple[MemoryDocument, ...]) -> str:
    sections = [
        f"<!-- memory-file: {item.source_path} -->\n{item.content.rstrip()}"
        for item in sorted(documents, key=lambda value: value.source_path)
    ]
    return "\n\n".join(sections).rstrip() + "\n" if sections else ""


def render_artifact_manifest(documents: tuple[MemoryDocument, ...]) -> str:
    return "\n".join(
        f"- {item.source_path} ({len(item.content)} chars)"
        for item in sorted(documents, key=lambda value: value.source_path)
    )
