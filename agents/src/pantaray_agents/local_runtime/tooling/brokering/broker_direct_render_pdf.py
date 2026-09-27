"""The render tool: a PDF's pages, drawn, so the model can look at them.

``documents.page_render`` does the drawing, in a child process that holds the
untrusted file. What this module owns is the policy around it: which file may
be opened, that it really is a PDF, and where the images are kept so the
conversation page and the next turn can both find them again. The bytes ride
the attachment path ``capture_screen`` puts a screenshot on, never the output,
which is durable history the memory tools read.
"""

from __future__ import annotations

import hashlib
import sys
from dataclasses import dataclass
from pathlib import Path

from pantaray_agents.local_runtime.runtime.local_image_store import (
    write_local_image_blob,
)
from pantaray_agents.local_runtime.tooling.documents import (
    RENDERED_PAGE_MEDIA_TYPE,
    DocumentExtractionError,
    DocumentTooLargeError,
    EncryptedDocumentError,
    PageOutOfRangeError,
    PageRenderTimeoutError,
    RenderedPage,
    render_pdf_pages,
)
from pantaray_agents.schema.agent.base import JSONValue

from .attachment_reference import (
    ATTACHMENT_BLOB_REF_PREFIX,
    ATTACHMENT_ID_HEX_LENGTH,
    TOOL_ATTACHMENT_REF_PREFIX,
)
from .broker_common import (
    BrokerContext,
    BrokerPolicyError,
    ensure_session_capabilities,
)
from .broker_direct_read import SAMPLE_BYTES, read_leading_bytes
from .broker_direct_read_document import (
    READ_DOCUMENT_TOO_LARGE,
    READ_DOCUMENT_TOO_LARGE_FIX_HINT,
    READ_DOCUMENT_UNREADABLE_FIX_HINT,
    document_format,
)
from .broker_outcome import UnprojectedBrokerToolOutcome
from .broker_protocol import ValidatedRenderPdfPageRequest
from .read_path_resolver import ReadTarget, action_reference_paths, resolve_read_target

RENDER_DOCUMENT_ENCRYPTED = "RENDER_DOCUMENT_ENCRYPTED"
RENDER_DOCUMENT_UNREADABLE = "RENDER_DOCUMENT_UNREADABLE"
RENDER_FORMAT_UNSUPPORTED = "RENDER_FORMAT_UNSUPPORTED"
RENDER_PAGE_OUT_OF_RANGE = "RENDER_PAGE_OUT_OF_RANGE"
RENDER_TIMED_OUT = "RENDER_TIMED_OUT"


@dataclass(frozen=True, slots=True)
class _StoredPage:
    """One drawn page, once it has a name and a place to live."""

    number: int
    display_path: str
    ref: str
    blob_ref: str
    storage_path: str
    byte_size: int
    sha256: str


async def run_render_pdf_page_executor(
    *, context: BrokerContext, request: ValidatedRenderPdfPageRequest
) -> UnprojectedBrokerToolOutcome:
    ensure_session_capabilities(context=context)
    target = resolve_read_target(context=context, raw_path=request.path)
    _reject_non_pdf(target)
    drawn = await _draw(target=target, pages=request.pages)
    stored = [
        _store(user_id=context.execution_session.user_id, page=page) for page in drawn
    ]
    output: dict[str, JSONValue] = {
        "kind": "pdf_pages",
        "path": target.display_path,
        # The refs are in the message as well as in the attachments: on the
        # string prompt path, the prompt text says where each image goes.
        "message": (
            f"Drew pages of {target.display_path}. "
            + " ".join(f"Page {page.number}: {page.ref}" for page in stored)
        ),
        # Durable history keeps this output, so an attachment names the image
        # by its user-scoped storage_path, never by path or by bytes.
        "attachments": [
            {
                "type": "file",
                "source_kind": "local_image_blob",
                "mime_type": RENDERED_PAGE_MEDIA_TYPE,
                "page_number": page.number,
                "path": page.display_path,
                "storage_path": page.storage_path,
                "ref": page.ref,
                "byte_size": page.byte_size,
            }
            for page in stored
        ],
    }
    return UnprojectedBrokerToolOutcome(
        status="success",
        output=output,
        search_text=None,
        file_paths=(target.display_path,),
        file_reference_paths=action_reference_paths(target),
        attachments=tuple(
            {
                "type": "file",
                "source_kind": "local_image_blob",
                "ref": page.ref,
                "blob_ref": page.blob_ref,
                "display_path": page.display_path,
                "mime_type": RENDERED_PAGE_MEDIA_TYPE,
                "byte_size": page.byte_size,
                "sha256": page.sha256,
                "storage_path": page.storage_path,
            }
            for page in stored
        ),
    )


def _reject_non_pdf(target: ReadTarget) -> None:
    """Refuse anything the renderer cannot open, before it is started.

    The same recognition the read tool uses, so a PDF saved without an
    extension is still drawn and a .docx never reaches PDFium.
    """

    if target.real_path.is_dir():
        raise _unsupported_format(target)
    sample = read_leading_bytes(target, limit=SAMPLE_BYTES)
    if document_format(filepath=target.real_path, sample=sample) != "pdf":
        raise _unsupported_format(target)


def _unsupported_format(target: ReadTarget) -> BrokerPolicyError:
    return BrokerPolicyError(
        f"Cannot draw pages of this file: {target.display_path}",
        code=RENDER_FORMAT_UNSUPPORTED,
        fix_hint=(
            "Only a PDF can be drawn here. Read a Word, PowerPoint or Excel "
            "file with read, which returns its text; read shows an image file "
            "as itself."
        ),
    )


async def _draw(*, target: ReadTarget, pages: list[int]) -> tuple[RenderedPage, ...]:
    try:
        return await render_pdf_pages(
            # The resolved real path: the renderer's sandbox admits the file by
            # the name the kernel walks, not by the one the caller typed.
            pdf_path=target.real_path,
            pages=pages,
            # The interpreter this helper is running on, by the name it was
            # started under: in the app that is the bundled runtime, and in a
            # development virtualenv it is the link that carries the
            # environment's packages, which its resolved target does not.
            python_executable=Path(sys.executable),
        )
    except EncryptedDocumentError as exc:
        raise BrokerPolicyError(
            f"Cannot draw a protected PDF: {target.display_path}: {exc}",
            code=RENDER_DOCUMENT_ENCRYPTED,
            fix_hint=(
                "Open the file in its application, remove the password, and "
                "save an unprotected copy to draw."
            ),
        ) from exc
    except DocumentTooLargeError as exc:
        raise BrokerPolicyError(
            f"Document is too large to draw: {target.display_path}: {exc}",
            code=READ_DOCUMENT_TOO_LARGE,
            fix_hint=READ_DOCUMENT_TOO_LARGE_FIX_HINT,
        ) from exc
    except PageOutOfRangeError as exc:
        raise BrokerPolicyError(
            f"{target.display_path} has {exc.total_units} pages: {exc}",
            code=RENDER_PAGE_OUT_OF_RANGE,
            fix_hint=f"Ask for page numbers between 1 and {exc.total_units}.",
        ) from exc
    except PageRenderTimeoutError as exc:
        raise BrokerPolicyError(
            f"Drawing {target.display_path} ran out of time: {exc}",
            code=RENDER_TIMED_OUT,
            fix_hint="Ask for fewer pages in one call, then call again.",
        ) from exc
    except DocumentExtractionError as exc:
        raise BrokerPolicyError(
            f"Cannot draw pages of this PDF: {target.display_path}: {exc}",
            code=RENDER_DOCUMENT_UNREADABLE,
            fix_hint=READ_DOCUMENT_UNREADABLE_FIX_HINT,
        ) from exc


def _store(*, user_id: str, page: RenderedPage) -> _StoredPage:
    """Name one page and store it, as ``capture_screen`` does a screenshot."""

    sha256 = hashlib.sha256(page.payload).hexdigest()
    attachment_id = sha256[:ATTACHMENT_ID_HEX_LENGTH]
    blob = write_local_image_blob(
        user_id=user_id, payload=page.payload, mime_type=RENDERED_PAGE_MEDIA_TYPE
    )
    return _StoredPage(
        number=page.number,
        display_path=(
            f"page-{page.number}-{attachment_id}{Path(blob.storage_path).suffix}"
        ),
        ref=f"{TOOL_ATTACHMENT_REF_PREFIX}{attachment_id}",
        blob_ref=f"{ATTACHMENT_BLOB_REF_PREFIX}{attachment_id}",
        storage_path=blob.storage_path,
        byte_size=len(page.payload),
        sha256=sha256,
    )


__all__ = ["run_render_pdf_page_executor"]
