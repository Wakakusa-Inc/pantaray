from __future__ import annotations

import base64
import binascii
import copy
import json
from typing import cast

from openai.types.responses.response_input_item_param import ResponseInputItemParam

from pantaray_llm.contracts.json_value import JSONValue
from pantaray_llm.contracts.tool_use import (
    LlmToolUseRequest,
    OpenAiContinuationMediaSlot,
    OpenAiToolContinuation,
)
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import (
    PROXY_CONTINUATION_PROVIDER_MISMATCH,
    PROXY_INVALID_INPUT,
    ProviderError,
)
from pantaray_llm.providers.media_projection import (
    has_equivalent_inline_projection,
    media_reference_text,
    verify_projected_media_payload,
)

_OPENAI_IMAGE_DATA_FIELD = "image_url"
_OPENAI_IMAGE_CONTENT_TYPE = "input_image"
# The inline field this adapter writes, plus the provider media fields it never
# writes: a continuation carrying any of them outside its own slot is rejected
# rather than forwarded upstream unaccounted for.
_OPENAI_PROVIDER_MEDIA_FIELDS = frozenset(
    {_OPENAI_IMAGE_DATA_FIELD, "file_data", "file_id", "file_url"}
)


def build_openai_blob_data_url(blob: UploadedBlob) -> str:
    return build_openai_data_url(payload=blob.payload, mime_type=blob.mime_type)


def build_openai_data_url(*, payload: bytes, mime_type: str) -> str:
    encoded = base64.b64encode(payload).decode("ascii")
    return f"data:{mime_type};base64,{encoded}"


def _decode_projected_data_url(
    *,
    data_url: str,
    slot: OpenAiContinuationMediaSlot,
) -> bytes:
    descriptor = slot.projection.materialized
    if descriptor is None:
        raise _continuation_error("OpenAI media slot has no projected media.")
    prefix = f"data:{descriptor.mime_type};base64,"
    if not data_url.startswith(prefix):
        raise _continuation_error(
            "OpenAI media payload does not match its projected MIME type."
        )
    try:
        return base64.b64decode(data_url.removeprefix(prefix), validate=True)
    except (binascii.Error, ValueError) as exc:
        raise _continuation_error("OpenAI media payload is not valid base64.") from exc


def _continuation_error(message: str) -> ProviderError:
    return ProviderError(
        status_code=400,
        code=PROXY_INVALID_INPUT,
        message=message,
    )


def _require_history_content(
    history: list[dict[str, object]],
    *,
    item_index: int,
    content_index: int,
) -> dict[str, object]:
    try:
        item = history[item_index]
        content = item["content"]
        if not isinstance(content, list):
            raise TypeError
        block = content[content_index]
        if not isinstance(block, dict):
            raise TypeError
    except (IndexError, KeyError, TypeError) as exc:
        raise _continuation_error(
            "OpenAI tool continuation contains an invalid media slot."
        ) from exc
    return block


def _require_slot_target(
    block: dict[str, object],
    *,
    slot: OpenAiContinuationMediaSlot,
) -> None:
    if slot.projection.state == "reference":
        if block.get("type") != "input_text" or block.get(
            "text"
        ) != media_reference_text(slot.projection):
            raise _continuation_error(
                "OpenAI media reference does not match its projection."
            )
        return
    if block.get("type") != _OPENAI_IMAGE_CONTENT_TYPE:
        raise _continuation_error(
            "OpenAI tool continuation media slot references the wrong content type."
        )


def _hydrate_openai_history(
    *,
    continuation: OpenAiToolContinuation,
) -> tuple[list[ResponseInputItemParam], set[str]]:
    history = cast(
        list[dict[str, object]],
        copy.deepcopy(continuation.history_items),
    )
    slot_positions: set[tuple[int, int]] = set()
    referenced_blob_refs: set[str] = set()
    for slot in continuation.media_slots:
        position = (slot.item_index, slot.content_index)
        if position in slot_positions:
            raise _continuation_error(
                "OpenAI tool continuation contains duplicate media slots."
            )
        slot_positions.add(position)
        block = _require_history_content(
            history,
            item_index=slot.item_index,
            content_index=slot.content_index,
        )
        _require_slot_target(block, slot=slot)
        unexpected_media_fields = (
            _OPENAI_PROVIDER_MEDIA_FIELDS - {slot.data_field}
        ).intersection(block)
        if unexpected_media_fields:
            raise _continuation_error(
                "OpenAI tool continuation contains provider media outside its slot."
            )
        projection = slot.projection
        if projection.state == "reference":
            continue
        inline_data = block.get(slot.data_field)
        if inline_data is not None and inline_data != "":
            raise _continuation_error(
                "OpenAI tool continuation must not contain inline media data."
            )
        referenced_blob_refs.add(projection.source.blob_ref)

    for item_index, item in enumerate(history):
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            if not any(field in block for field in _OPENAI_PROVIDER_MEDIA_FIELDS):
                continue
            if (item_index, content_index) not in slot_positions:
                raise _continuation_error(
                    "OpenAI tool continuation contains unreferenced inline media."
                )
    return cast(list[ResponseInputItemParam], history), referenced_blob_refs


def serialize_openai_history(
    *,
    items: list[ResponseInputItemParam],
    media_slots: list[OpenAiContinuationMediaSlot],
) -> list[dict[str, JSONValue]]:
    history = cast(list[dict[str, object]], copy.deepcopy(items))
    slots_by_position = {
        (slot.item_index, slot.content_index): slot for slot in media_slots
    }
    if len(slots_by_position) != len(media_slots):
        raise _continuation_error(
            "OpenAI tool continuation contains duplicate media slots."
        )
    found_positions: set[tuple[int, int]] = set()
    for item_index, item in enumerate(history):
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_index, block in enumerate(content):
            if not isinstance(block, dict):
                continue
            position = (item_index, content_index)
            slot = slots_by_position.get(position)
            if slot is not None and slot.projection.state == "reference":
                _require_slot_target(block, slot=slot)
                found_positions.add(position)
                continue
            if _OPENAI_IMAGE_DATA_FIELD in block:
                if slot is None:
                    raise _continuation_error(
                        "OpenAI tool continuation cannot retain unreferenced inline media."
                    )
                _require_slot_target(block, slot=slot)
                data_url = block.get(slot.data_field)
                if not isinstance(data_url, str):
                    raise _continuation_error(
                        "OpenAI tool continuation media slot has invalid inline data."
                    )
                payload = _decode_projected_data_url(data_url=data_url, slot=slot)
                materialized = slot.projection.materialized
                if materialized is None:  # pragma: no cover - schema invariant
                    raise AssertionError("inline projection omitted materialized media")
                verify_projected_media_payload(
                    projection=slot.projection,
                    payload=payload,
                    mime_type=materialized.mime_type,
                )
                block.pop(slot.data_field)
                found_positions.add(position)
            elif slot is not None:
                raise _continuation_error(
                    "OpenAI tool continuation media slot does not reference inline media."
                )
    if found_positions != set(slots_by_position):
        raise _continuation_error(
            "OpenAI tool continuation contains an invalid media slot."
        )
    return cast(list[dict[str, JSONValue]], history)


def build_openai_tool_input(
    *,
    initial_input: list[ResponseInputItemParam],
    initial_media_slots: list[OpenAiContinuationMediaSlot],
    tool_use: LlmToolUseRequest | None,
) -> tuple[
    list[ResponseInputItemParam],
    list[OpenAiContinuationMediaSlot],
    set[str],
    int,
]:
    if tool_use is None:
        return (
            initial_input,
            initial_media_slots,
            {slot.projection.source.blob_ref for slot in initial_media_slots},
            0,
        )
    continuation = tool_use.continuation
    result = tool_use.tool_result
    # The contract pairs a continuation with its tool_result, or neither.
    if continuation is None or result is None:
        return (
            initial_input,
            initial_media_slots,
            {slot.projection.source.blob_ref for slot in initial_media_slots},
            0,
        )
    if not isinstance(continuation, OpenAiToolContinuation):
        raise ProviderError(
            status_code=400,
            code=PROXY_CONTINUATION_PROVIDER_MISMATCH,
            message="OpenAI profiles require an OpenAI tool continuation.",
        )
    items, referenced_blob_refs = _hydrate_openai_history(
        continuation=continuation,
    )
    call_items = [
        item
        for item in items
        if isinstance(item, dict) and item.get("type") == "function_call"
    ]
    if not call_items or call_items[-1].get("call_id") != result.call_id:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message="OpenAI tool_result.call_id does not match the continuation.",
        )
    if call_items[-1].get("name") != result.name:
        raise ProviderError(
            status_code=400,
            code=PROXY_INVALID_INPUT,
            message="OpenAI tool_result.name does not match the continuation.",
        )
    items.append(
        cast(
            ResponseInputItemParam,
            {
                "type": "function_call_output",
                "call_id": result.call_id,
                "output": json.dumps(result.output, ensure_ascii=False),
            },
        )
    )
    history_slot_count = len(continuation.media_slots)
    history_projections = tuple(slot.projection for slot in continuation.media_slots)
    initial_history = cast(
        list[dict[str, object]],
        copy.deepcopy(initial_input),
    )
    current_content: list[dict[str, object]] = []
    current_slots: list[OpenAiContinuationMediaSlot] = []
    for slot in initial_media_slots:
        blob_ref = slot.projection.source.blob_ref
        referenced_blob_refs.add(blob_ref)
        if has_equivalent_inline_projection(
            projection=slot.projection,
            history=history_projections,
        ):
            continue
        block = _require_history_content(
            initial_history,
            item_index=slot.item_index,
            content_index=slot.content_index,
        )
        current_slots.append(
            slot.model_copy(
                update={
                    "item_index": len(items),
                    "content_index": len(current_content),
                }
            )
        )
        current_content.append(block)
    if current_content:
        items.append(
            cast(
                ResponseInputItemParam,
                {"role": "user", "content": current_content},
            )
        )
    media_slots = [*continuation.media_slots, *current_slots]
    return items, media_slots, referenced_blob_refs, history_slot_count


__all__ = [
    "build_openai_blob_data_url",
    "build_openai_data_url",
    "build_openai_tool_input",
    "serialize_openai_history",
]
