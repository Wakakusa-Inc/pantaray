"""Brokered PDF page rendering tool definition."""

from __future__ import annotations

from pantaray_agents.local_runtime.tooling.brokering.broker_protocol import (
    RenderPdfPageToolArgs,
)
from pantaray_agents.local_runtime.tooling.documents import MAX_RENDERED_PAGES

from .base import (
    ToolDefinition,
    ToolGuideSpec,
    ToolSpec,
    tool_execution_policy,
)
from .broker_tool_input_schema import (
    BrokerToolFieldPresentation,
    broker_tool_input_spec_from_model,
)

RENDER_PDF_PAGE_TOOL_ID = "render_pdf_page"
# Declared like every tool's, but never applied: this tool runs alone in its
# turn, and the renderer ends itself at its own limit.
RENDER_PDF_PAGE_TIMEOUT_MS = 30_000

RENDER_PDF_PAGE_FIELD_PRESENTATION = (
    BrokerToolFieldPresentation(
        name="path",
        prompt_type="string",
        description=(
            "Local path of a PDF, the same path read takes. Allowed paths "
            "follow Read/search access in Workspace Path Rules."
        ),
        llm_order=10,
    ),
    BrokerToolFieldPresentation(
        name="pages",
        prompt_type="array",
        description=(
            "1-based page numbers to look at, listed one by one: pages 1 to 5 "
            f"is [1, 2, 3, 4, 5]. At most {MAX_RENDERED_PAGES} per call, with "
            "no repeats."
        ),
        llm_order=20,
    ),
)

RENDER_PDF_PAGE_TOOL = ToolDefinition.from_spec(
    ToolSpec(
        tool_id=RENDER_PDF_PAGE_TOOL_ID,
        name="Look At PDF Pages",
        description="Draw pages of a local PDF as images this step can see.",
        guide=ToolGuideSpec(
            what=(
                "Draw the named pages of a PDF as images and attach them to "
                "this step, so you can look at the page instead of reading the "
                "text it stores."
            ),
            when=(
                "Use when a PDF's appearance carries the meaning: a page read "
                "listed in pages_without_text, a scan, a figure, a table whose "
                "layout is the information, a signature or a stamp."
            ),
            pitfalls=(
                "read is still how you get a document's contents; this tool "
                "only shows how a page looks and returns no text. Page numbers "
                "are the ones read uses: the values in pages_without_text, or "
                f'the N in an images[].ref of "page N". At most '
                f"{MAX_RENDERED_PAGES} pages per call. The images stay with "
                "this step until the context window is rebuilt, and are not "
                "sent again after that, so draw a page again if you no longer "
                "see it. A subagent cannot see them, so do not "
                "ask one to look at a page. Only PDFs can be drawn: read a "
                "Word, PowerPoint or Excel file for its text, and read shows "
                "an image file as itself."
            ),
        ),
        execution_policy=tool_execution_policy(
            intent_class="read_only",
            required_capabilities=("scoped_read",),
            default_timeout_ms=RENDER_PDF_PAGE_TIMEOUT_MS,
        ),
        input_spec=broker_tool_input_spec_from_model(
            model=RenderPdfPageToolArgs,
            fields=RENDER_PDF_PAGE_FIELD_PRESENTATION,
            description="Draw pages of a local PDF as images.",
        ),
        output_schema={
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["pdf_pages"]},
                "path": {"type": "string"},
                "message": {"type": "string"},
                "attachments": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": ["file"]},
                            "source_kind": {
                                "type": "string",
                                "enum": ["local_image_blob"],
                            },
                            "mime_type": {"type": "string"},
                            "page_number": {"type": "integer"},
                            "path": {"type": "string"},
                            "storage_path": {"type": "string"},
                            "ref": {"type": "string"},
                            "byte_size": {"type": "integer"},
                        },
                        "required": [
                            "type",
                            "source_kind",
                            "mime_type",
                            "page_number",
                            "path",
                            "storage_path",
                            "ref",
                            "byte_size",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["kind", "path", "message", "attachments"],
            "additionalProperties": False,
        },
    )
)

__all__ = [
    "RENDER_PDF_PAGE_TIMEOUT_MS",
    "RENDER_PDF_PAGE_TOOL",
    "RENDER_PDF_PAGE_TOOL_ID",
]
