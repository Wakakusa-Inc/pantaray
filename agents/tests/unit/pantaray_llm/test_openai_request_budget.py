from __future__ import annotations

import hashlib
import io
from typing import cast

import pytest
from openai.types.responses.response_create_params import (
    ResponseCreateParamsNonStreaming,
)
from PIL import Image

from pantaray_llm.contracts.media import LlmMediaDescriptor, LlmMediaProjection
from pantaray_llm.contracts.tool_use import OpenAiContinuationMediaSlot
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import ProviderError
from pantaray_llm.providers.media_projection import (
    media_reference_text,
    original_media_projection,
)
from pantaray_llm.providers.openai_responses.request_budget import (
    measure_openai_request_bytes,
    prepare_openai_request,
)
from pantaray_llm.providers.openai_responses.tool_use import build_openai_data_url


def _png(*, width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    for y_pos in range(height):
        for x_pos in range(width):
            value = (x_pos * 71 + y_pos * 149) % 256
            pixels[x_pos, y_pos] = (value, (value * 43) % 256, (value * 89) % 256)
    output = io.BytesIO()
    image.save(output, format="PNG")
    image.close()
    return output.getvalue()


def _request(payload: bytes) -> ResponseCreateParamsNonStreaming:
    return cast(
        ResponseCreateParamsNonStreaming,
        {
            "model": "gpt-test",
            "input": [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": "inspect"},
                        {
                            "type": "input_image",
                            "image_url": build_openai_data_url(
                                payload=payload,
                                mime_type="image/png",
                            ),
                            "detail": "high",
                        },
                    ],
                }
            ],
            "max_output_tokens": 10,
            "store": False,
            "stream": False,
        },
    )


def _media(
    payload: bytes,
    *,
    application_ref: str | None = None,
) -> tuple[OpenAiContinuationMediaSlot, UploadedBlob]:
    descriptor = LlmMediaDescriptor(
        blob_ref="image-1",
        mime_type="image/png",
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        application_ref=application_ref,
    )
    blob = UploadedBlob(
        field_name="image-1",
        payload=payload,
        mime_type="image/png",
    )
    return (
        OpenAiContinuationMediaSlot(
            item_index=0,
            content_index=1,
            data_field="image_url",
            projection=original_media_projection(
                descriptor=descriptor,
                source_blob=blob,
            ),
        ),
        blob,
    )


def _image_url(request: ResponseCreateParamsNonStreaming) -> str:
    input_items = request["input"]
    assert isinstance(input_items, list)
    content = input_items[0]["content"]
    assert isinstance(content, list)
    image_url = content[1]["image_url"]
    assert isinstance(image_url, str)
    return image_url


@pytest.mark.asyncio
async def test_resize_projection_matches_openai_request_and_replays_from_source() -> (
    None
):
    payload = _png(width=140, height=100)
    create_kwargs = _request(payload)
    slot, blob = _media(payload)

    prepared = await prepare_openai_request(
        create_kwargs=create_kwargs,
        media_slots=[slot],
        uploaded_blobs={"image-1": blob},
        history_media_slot_count=0,
        max_request_bytes=900,
        min_long_edge_px=24,
    )

    assert prepared.request_size_bytes <= 900
    projection = prepared.media_slots[0].projection
    assert projection.materialized is not None
    assert projection.image_recipe is not None
    assert projection.materialized.mime_type == "image/webp"
    encoded_payload = _image_url(prepared.create_kwargs).split(",", 1)[1]
    assert len(encoded_payload) > 0
    assert _image_url(create_kwargs).startswith("data:image/png;base64,")

    replayed = await prepare_openai_request(
        create_kwargs=prepared.create_kwargs,
        media_slots=prepared.media_slots,
        uploaded_blobs={"image-1": blob},
        history_media_slot_count=1,
        max_request_bytes=900,
        min_long_edge_px=24,
    )
    assert _image_url(replayed.create_kwargs) == _image_url(prepared.create_kwargs)
    assert replayed.media_slots == prepared.media_slots


@pytest.mark.asyncio
async def test_openai_history_image_can_become_application_reference() -> None:
    payload = _png(width=140, height=100)
    slot, blob = _media(payload, application_ref="tool_attachment:image-1")
    reference_projection = LlmMediaProjection(
        state="reference",
        source=slot.projection.source,
    )
    reference_request = _request(payload)
    reference_input = reference_request["input"]
    assert isinstance(reference_input, list)
    reference_content = reference_input[0]["content"]
    assert isinstance(reference_content, list)
    reference_content[1] = {
        "type": "input_text",
        "text": media_reference_text(reference_projection),
    }
    reference_size = measure_openai_request_bytes(reference_request)

    prepared = await prepare_openai_request(
        create_kwargs=_request(payload),
        media_slots=[slot],
        uploaded_blobs={"image-1": blob},
        history_media_slot_count=1,
        max_request_bytes=reference_size,
        min_long_edge_px=24,
    )

    assert prepared.media_slots[0].projection == reference_projection
    prepared_input = prepared.create_kwargs["input"]
    assert isinstance(prepared_input, list)
    prepared_content = prepared_input[0]["content"]
    assert isinstance(prepared_content, list)
    assert prepared_content[1] == reference_content[1]


@pytest.mark.asyncio
async def test_openai_current_image_is_not_replaced_with_reference() -> None:
    payload = _png(width=140, height=100)
    slot, blob = _media(payload, application_ref="tool_attachment:image-1")

    with pytest.raises(ProviderError) as exc_info:
        await prepare_openai_request(
            create_kwargs=_request(payload),
            media_slots=[slot],
            uploaded_blobs={"image-1": blob},
            history_media_slot_count=0,
            max_request_bytes=100,
            min_long_edge_px=24,
        )

    assert exc_info.value.details["reason"] == "active_media_too_large"


@pytest.mark.asyncio
async def test_openai_text_only_request_fails_explicitly_when_over_limit() -> None:
    create_kwargs = cast(
        ResponseCreateParamsNonStreaming,
        {
            "model": "gpt-test",
            "input": "text only",
            "store": False,
            "stream": False,
        },
    )

    with pytest.raises(ProviderError) as exc_info:
        await prepare_openai_request(
            create_kwargs=create_kwargs,
            media_slots=[],
            uploaded_blobs={},
            history_media_slot_count=0,
            max_request_bytes=1,
        )

    assert exc_info.value.details["reason"] == "request_without_reducible_images"
