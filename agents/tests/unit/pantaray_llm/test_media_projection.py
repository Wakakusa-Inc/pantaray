from __future__ import annotations

import hashlib
import io
from collections.abc import Callable

import pytest
from PIL import Image

from pantaray_llm.contracts.media import LlmMediaDescriptor
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import PROXY_INVALID_INPUT, ProviderError
from pantaray_llm.providers import media_projection

_ORIENTATIONS = tuple(range(1, 9))


def _still_image(
    *,
    image_format: str,
    orientation: int | None,
) -> bytes:
    image = Image.new("RGB", (11, 7), color=(20, 40, 60))
    output = io.BytesIO()
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    image.save(output, format=image_format, exif=exif)
    image.close()
    return output.getvalue()


def _animated_gif() -> bytes:
    first = Image.new("RGB", (11, 7), color=(20, 40, 60))
    second = Image.new("RGB", (11, 7), color=(60, 40, 20))
    output = io.BytesIO()
    first.save(
        output,
        format="GIF",
        save_all=True,
        append_images=[second],
        duration=10,
        loop=0,
    )
    first.close()
    second.close()
    return output.getvalue()


def _blob(payload: bytes) -> tuple[LlmMediaDescriptor, UploadedBlob]:
    descriptor = LlmMediaDescriptor(
        blob_ref="image-1",
        mime_type="image/png",
        byte_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )
    return descriptor, UploadedBlob(
        field_name=descriptor.blob_ref,
        payload=payload,
        mime_type=descriptor.mime_type,
    )


def _request_media(
    payload: bytes, *, is_history: bool = False
) -> tuple[media_projection.RequestMedia,]:
    descriptor, blob = _blob(payload)
    projection = media_projection.original_media_projection(
        descriptor=descriptor,
        source_blob=blob,
    )
    return (
        media_projection.RequestMedia(
            position=(0, 0),
            projection=projection,
            source_blob=blob,
            is_history=is_history,
        ),
    )


@pytest.mark.parametrize("orientation", _ORIENTATIONS)
@pytest.mark.parametrize("image_format", ["JPEG", "PNG", "WEBP"])
def test_inspected_shape_matches_decoded_shape(
    *,
    image_format: str,
    orientation: int,
) -> None:
    payload = _still_image(image_format=image_format, orientation=orientation)
    if image_format == "PNG":
        assert payload.index(b"eXIf") < payload.index(b"IDAT")

    inspected = media_projection._source_image_shape(payload)
    decoded = media_projection._decode_source_image(payload)

    try:
        assert inspected == decoded.size
    finally:
        decoded.close()


@pytest.mark.parametrize(
    "payload_factory",
    [
        pytest.param(
            lambda: _still_image(image_format="PNG", orientation=None),
            id="png-without-exif",
        ),
        pytest.param(_animated_gif, id="animated-gif-frame-zero"),
    ],
)
def test_inspected_shape_matches_decoded_shape_without_orientation(
    payload_factory: Callable[[], bytes],
) -> None:
    payload = payload_factory()

    inspected = media_projection._source_image_shape(payload)
    decoded = media_projection._decode_source_image(payload)

    try:
        assert inspected == decoded.size == (11, 7)
    finally:
        decoded.close()


@pytest.mark.parametrize("orientation", [None, 6], ids=["without-exif", "with-exif"])
def test_png_inspection_does_not_load_pixels(
    monkeypatch: pytest.MonkeyPatch,
    orientation: int | None,
) -> None:
    payload = _still_image(image_format="PNG", orientation=orientation)
    opened = Image.open(io.BytesIO(payload))
    load_calls = 0

    def reject_load() -> None:
        nonlocal load_calls
        load_calls += 1
        raise AssertionError("inspection must not load image pixels")

    monkeypatch.setattr(opened, "load", reject_load)
    monkeypatch.setattr(media_projection.Image, "open", lambda _stream: opened)

    assert media_projection._source_image_shape(payload) == (
        (7, 11) if orientation == 6 else (11, 7)
    )
    assert load_calls == 0


def test_original_projection_enforces_call_time_pixel_limit_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _still_image(image_format="PNG", orientation=None)
    descriptor, blob = _blob(payload)
    decode_calls = 0

    def reject_decode(_payload: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        raise AssertionError("rejected image must not be decoded")

    monkeypatch.setattr(
        media_projection,
        "IMAGE_MAX_DECODED_PIXELS_PER_REQUEST",
        76,
    )
    monkeypatch.setattr(media_projection, "_decode_source_image", reject_decode)

    with pytest.raises(ProviderError) as exc_info:
        media_projection.original_media_projection(
            descriptor=descriptor,
            source_blob=blob,
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.code == PROXY_INVALID_INPUT
    assert error.message == "Image input exceeds the decoded pixel limit."
    assert error.details == {"reason": "invalid_image"}
    assert decode_calls == 0


def test_corrupt_image_uses_invalid_image_error_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"not-an-image"
    descriptor, blob = _blob(payload)
    decode_calls = 0

    def reject_decode(_payload: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        raise AssertionError("rejected image must not be decoded")

    monkeypatch.setattr(media_projection, "_decode_source_image", reject_decode)

    with pytest.raises(ProviderError) as exc_info:
        media_projection.original_media_projection(
            descriptor=descriptor,
            source_blob=blob,
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.code == PROXY_INVALID_INPUT
    assert error.message == "Image input could not be decoded."
    assert error.details == {"reason": "invalid_image"}
    assert decode_calls == 0


def test_decompression_bomb_uses_pixel_limit_error_before_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b"stubbed-image"
    descriptor, blob = _blob(payload)
    decode_calls = 0

    def raise_bomb(_stream: io.BytesIO) -> Image.Image:
        raise Image.DecompressionBombError("too many pixels")

    def reject_decode(_payload: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        raise AssertionError("rejected image must not be decoded")

    monkeypatch.setattr(media_projection.Image, "open", raise_bomb)
    monkeypatch.setattr(media_projection, "_decode_source_image", reject_decode)

    with pytest.raises(ProviderError) as exc_info:
        media_projection.original_media_projection(
            descriptor=descriptor,
            source_blob=blob,
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.code == PROXY_INVALID_INPUT
    assert error.message == "Image input exceeds the decoded pixel limit."
    assert error.details == {"reason": "invalid_image"}
    assert decode_calls == 0


def test_aggregate_admission_counts_each_slot_before_decode_or_render(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _still_image(image_format="PNG", orientation=None)
    descriptor, blob = _blob(payload)
    projection = media_projection.original_media_projection(
        descriptor=descriptor,
        source_blob=blob,
    )
    request_media = tuple(
        media_projection.RequestMedia(
            position=(0, index),
            projection=projection,
            source_blob=blob,
            is_history=index == 0,
        )
        for index in range(2)
    )
    inspect_calls = 0
    decode_calls = 0
    render_calls = 0
    measure_calls = 0
    inspect = media_projection._source_image_shape

    def track_inspect(source: bytes) -> tuple[int, int]:
        nonlocal inspect_calls
        inspect_calls += 1
        return inspect(source)

    def reject_decode(_payload: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        raise AssertionError("rejected request must not decode images")

    def reject_render(
        _prepared: tuple[media_projection.PreparedMedia, ...],
    ) -> bytes:
        nonlocal render_calls
        render_calls += 1
        raise AssertionError("rejected request must not render")

    def reject_measure(_request: bytes) -> int:
        nonlocal measure_calls
        measure_calls += 1
        raise AssertionError("rejected request must not be measured")

    monkeypatch.setattr(
        media_projection,
        "IMAGE_MAX_DECODED_PIXELS_PER_REQUEST",
        100,
    )
    monkeypatch.setattr(media_projection, "_source_image_shape", track_inspect)
    monkeypatch.setattr(media_projection, "_decode_source_image", reject_decode)

    with pytest.raises(ProviderError) as exc_info:
        media_projection.fit_request_media_to_budget(
            media=request_media,
            render=reject_render,
            measure=reject_measure,
            max_request_bytes=1_000_000,
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.code == PROXY_INVALID_INPUT
    assert error.message == "Image inputs exceed the aggregate decoded pixel limit."
    assert error.details == {"reason": "invalid_image"}
    assert inspect_calls == 2
    assert decode_calls == render_calls == measure_calls == 0


def test_baseline_acceptance_renders_and_measures_once_without_decode(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _still_image(image_format="PNG", orientation=None)
    request_media = _request_media(payload)
    events: list[str] = []
    decode_calls = 0
    decode = media_projection._decode_source_image

    def track_decode(source: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        return decode(source)

    def render(_prepared: tuple[media_projection.PreparedMedia, ...]) -> int:
        events.append("render")
        return len(events)

    def measure(_request: int) -> int:
        events.append("measure")
        return 100

    monkeypatch.setattr(media_projection, "_decode_source_image", track_decode)

    fitted = media_projection.fit_request_media_to_budget(
        media=request_media,
        render=render,
        measure=measure,
        max_request_bytes=100,
    )

    assert fitted.request_size_bytes == 100
    assert events == ["render", "measure"]
    assert decode_calls == 0


def test_first_resize_acceptance_preserves_render_measure_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = _still_image(image_format="PNG", orientation=None)
    request_media = _request_media(payload)
    events: list[str] = []
    decode_calls = 0
    decode = media_projection._decode_source_image

    def track_decode(source: bytes) -> Image.Image:
        nonlocal decode_calls
        decode_calls += 1
        return decode(source)

    def render(_prepared: tuple[media_projection.PreparedMedia, ...]) -> int:
        events.append("render")
        return len(events)

    def measure(request: int) -> int:
        events.append("measure")
        return 101 if request == 1 else 100

    monkeypatch.setattr(media_projection, "_decode_source_image", track_decode)

    fitted = media_projection.fit_request_media_to_budget(
        media=request_media,
        render=render,
        measure=measure,
        max_request_bytes=100,
        min_long_edge_px=1,
    )

    assert fitted.request_size_bytes == 100
    assert fitted.media[0].projection.image_recipe is not None
    assert events == ["render", "measure", "render", "measure"]
    assert decode_calls == 1  # Baseline: 0; first resize candidate: 1.


@pytest.mark.parametrize(
    ("media_kind", "reason"),
    [
        ("none", "request_without_reducible_images"),
        ("active", "active_media_too_large"),
        ("history", "media_too_large"),
    ],
)
def test_request_too_large_reason_branches_are_preserved(
    media_kind: str,
    reason: str,
) -> None:
    payload = _still_image(image_format="PNG", orientation=None)
    if media_kind == "none":
        request_media: tuple[media_projection.RequestMedia, ...] = ()
    else:
        request_media = _request_media(payload, is_history=media_kind == "history")

    with pytest.raises(ProviderError) as exc_info:
        media_projection.fit_request_media_to_budget(
            media=request_media,
            render=lambda _prepared: b"request",
            measure=lambda _request: 101,
            max_request_bytes=100,
            min_long_edge_px=1,
        )

    error = exc_info.value
    assert error.status_code == 400
    assert error.code == PROXY_INVALID_INPUT
    assert error.details is not None
    assert error.details["reason"] == reason


@pytest.mark.parametrize(
    "application_ref",
    ["tool_attachment:abc123", "user_attachment:abc123"],
)
def test_media_descriptor_accepts_both_attachment_ref_namespaces(
    application_ref: str,
) -> None:
    descriptor = LlmMediaDescriptor(
        blob_ref="attachment_blob_abc123",
        mime_type="image/png",
        byte_size=12,
        sha256="a" * 64,
        application_ref=application_ref,
    )

    assert descriptor.application_ref == application_ref


@pytest.mark.parametrize(
    "application_ref",
    ["workspace_file:abc123", "user_attachment:", "abc123"],
)
def test_media_descriptor_rejects_unknown_attachment_ref(
    application_ref: str,
) -> None:
    with pytest.raises(ValueError, match="application_ref"):
        LlmMediaDescriptor(
            blob_ref="attachment_blob_abc123",
            mime_type="image/png",
            byte_size=12,
            sha256="a" * 64,
            application_ref=application_ref,
        )
