"""Validation for multipart OpenAI content blocks."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping

from pantaray_llm.contracts.conversation import LlmConversation, LlmTurnAssistantItem
from pantaray_llm.contracts.media import LlmMediaDescriptor
from pantaray_llm.contracts.request import LlmInputImageBlock, LlmMessage
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import PROXY_INVALID_INPUT, ProviderError
from pantaray_llm.providers.openai_responses.request_limits import (
    OPENAI_MAX_REQUEST_BYTES,
)


def require_uploaded_blob(
    *,
    descriptor: LlmMediaDescriptor,
    uploaded_blobs: Mapping[str, UploadedBlob],
) -> UploadedBlob:
    """Return the referenced blob after verifying its declared integrity."""

    blob = uploaded_blobs.get(descriptor.blob_ref)
    if blob is None:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message=f"Missing uploaded blob: {descriptor.blob_ref}.",
        )
    if descriptor.mime_type != blob.mime_type:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message=f"Uploaded blob mime_type mismatch: {descriptor.blob_ref}.",
        )
    if descriptor.byte_size != len(blob.payload):
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message=f"Uploaded blob byte_size mismatch: {descriptor.blob_ref}.",
        )
    actual_sha256 = hashlib.sha256(blob.payload).hexdigest()
    if descriptor.sha256 != actual_sha256:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message=f"Uploaded blob sha256 mismatch: {descriptor.blob_ref}.",
        )
    return blob


def reject_unreferenced_uploads(
    *,
    uploaded_blobs: Mapping[str, UploadedBlob],
    referenced_blob_refs: set[str],
) -> None:
    """Reject multipart blobs that are absent from the typed request body."""

    unexpected_uploads = sorted(set(uploaded_blobs) - referenced_blob_refs)
    if unexpected_uploads:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message=f"Unexpected uploaded blobs: {', '.join(unexpected_uploads)}.",
        )


def reject_oversized_media_references(
    *,
    messages: list[LlmMessage],
    conversation: LlmConversation | None,
) -> None:
    """Reject repeated media references before provider payload construction."""

    blocks = [block for message in messages for block in message.content]
    # An assistant item carries no input blocks; every other conversation item
    # sends its own media on the same request as the messages above.
    blocks.extend(
        block
        for item in conversation or []
        if not isinstance(item, LlmTurnAssistantItem)
        for block in item.content
    )
    referenced_media_bytes = 0
    for block in blocks:
        if isinstance(block, LlmInputImageBlock):
            referenced_media_bytes += block.image.byte_size
    if referenced_media_bytes > OPENAI_MAX_REQUEST_BYTES:
        raise request_too_large_error(
            request_size_bytes=referenced_media_bytes,
            max_request_bytes=OPENAI_MAX_REQUEST_BYTES,
            reason="media_references_too_large",
        )


def request_too_large_error(
    *,
    request_size_bytes: int,
    max_request_bytes: int,
    reason: str,
) -> ProviderError:
    return ProviderError(
        status_code=400,
        code=PROXY_INVALID_INPUT,
        message="LLM request could not fit the provider request-size limit.",
        details={
            "reason": reason,
            "request_size_bytes": request_size_bytes,
            "max_request_size_bytes": max_request_bytes,
        },
    )


__all__ = [
    "reject_oversized_media_references",
    "reject_unreferenced_uploads",
    "request_too_large_error",
    "require_uploaded_blob",
]
