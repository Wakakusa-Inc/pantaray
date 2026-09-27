"""OpenAI wire measurement and provider-neutral media budget integration."""

from __future__ import annotations

import asyncio
import copy
import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import cast

from openai.types.responses.response_create_params import (
    ResponseCreateParamsNonStreaming,
)
from openai.types.responses.response_input_item_param import ResponseInputItemParam

from pantaray_llm.contracts.tool_use import OpenAiContinuationMediaSlot
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.providers.media_projection import (
    PreparedMedia,
    RequestMedia,
    fit_request_media_to_budget,
    media_reference_text,
)
from pantaray_llm.providers.openai_responses.request_limits import (
    OPENAI_MAX_REQUEST_BYTES,
)
from pantaray_llm.providers.openai_responses.tool_use import build_openai_data_url
from pantaray_llm.providers.uploaded_content import require_uploaded_blob


@dataclass(frozen=True, slots=True)
class PreparedOpenAiRequest:
    create_kwargs: ResponseCreateParamsNonStreaming
    media_slots: list[OpenAiContinuationMediaSlot]
    request_size_bytes: int


def measure_openai_request_bytes(
    create_kwargs: ResponseCreateParamsNonStreaming,
) -> int:
    return len(
        json.dumps(
            create_kwargs,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    )


async def prepare_openai_request(
    *,
    create_kwargs: ResponseCreateParamsNonStreaming,
    media_slots: list[OpenAiContinuationMediaSlot],
    uploaded_blobs: Mapping[str, UploadedBlob],
    history_media_slot_count: int,
    max_request_bytes: int | None = None,
    min_long_edge_px: int = 640,
) -> PreparedOpenAiRequest:
    request_limit = (
        max_request_bytes if max_request_bytes is not None else OPENAI_MAX_REQUEST_BYTES
    )
    return await asyncio.to_thread(
        _prepare_openai_request_sync,
        create_kwargs=create_kwargs,
        media_slots=media_slots,
        uploaded_blobs=uploaded_blobs,
        history_media_slot_count=history_media_slot_count,
        max_request_bytes=request_limit,
        min_long_edge_px=min_long_edge_px,
    )


def _prepare_openai_request_sync(
    *,
    create_kwargs: ResponseCreateParamsNonStreaming,
    media_slots: list[OpenAiContinuationMediaSlot],
    uploaded_blobs: Mapping[str, UploadedBlob],
    history_media_slot_count: int,
    max_request_bytes: int,
    min_long_edge_px: int,
) -> PreparedOpenAiRequest:
    if not 0 <= history_media_slot_count <= len(media_slots):
        raise ValueError("history_media_slot_count is outside media_slots")
    request_media = tuple(
        RequestMedia(
            position=(slot.item_index, slot.content_index),
            projection=slot.projection,
            source_blob=(
                require_uploaded_blob(
                    descriptor=slot.projection.source,
                    uploaded_blobs=uploaded_blobs,
                )
                if slot.projection.state == "inline"
                else None
            ),
            is_history=index < history_media_slot_count,
        )
        for index, slot in enumerate(media_slots)
    )
    fitted = fit_request_media_to_budget(
        media=request_media,
        render=lambda prepared: _render_openai_request(
            create_kwargs=create_kwargs,
            media_slots=media_slots,
            prepared=prepared,
        ),
        measure=measure_openai_request_bytes,
        max_request_bytes=max_request_bytes,
        min_long_edge_px=min_long_edge_px,
    )
    projections = {item.position: item.projection for item in fitted.media}
    return PreparedOpenAiRequest(
        create_kwargs=fitted.request,
        media_slots=[
            slot.model_copy(
                update={
                    "projection": projections[(slot.item_index, slot.content_index)]
                }
            )
            for slot in media_slots
        ],
        request_size_bytes=fitted.request_size_bytes,
    )


def _render_openai_request(
    *,
    create_kwargs: ResponseCreateParamsNonStreaming,
    media_slots: list[OpenAiContinuationMediaSlot],
    prepared: tuple[PreparedMedia, ...],
) -> ResponseCreateParamsNonStreaming:
    rendered = copy.deepcopy(create_kwargs)
    if not prepared:
        return rendered
    raw_input = rendered.get("input")
    if not isinstance(raw_input, list):
        raise ValueError("OpenAI input must be a list")
    input_items = cast(list[dict[str, object]], raw_input)
    slots_by_position = {
        (slot.item_index, slot.content_index): slot for slot in media_slots
    }
    for item in prepared:
        item_index, content_index = item.position
        content = input_items[item_index].get("content")
        if not isinstance(content, list):
            raise ValueError("OpenAI media slot must reference content")
        if item.projection.state == "reference":
            content[content_index] = {
                "type": "input_text",
                "text": media_reference_text(item.projection),
            }
            continue
        materialized = item.materialized
        if materialized is None:  # pragma: no cover - projection invariant
            raise AssertionError("inline projection omitted materialized media")
        block = content[content_index]
        if not isinstance(block, dict):
            raise ValueError("OpenAI media slot must reference an object")
        slot = slots_by_position[item.position]
        block[slot.data_field] = build_openai_data_url(
            payload=materialized.payload,
            mime_type=materialized.mime_type,
        )
    rendered["input"] = cast(list[ResponseInputItemParam], input_items)
    return rendered


__all__ = [
    "PreparedOpenAiRequest",
    "measure_openai_request_bytes",
    "prepare_openai_request",
]
