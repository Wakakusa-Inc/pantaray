"""Provider-neutral media projection, replay, and request fitting."""

from __future__ import annotations

import hashlib
import io
import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from PIL import Image, UnidentifiedImageError, features
from PIL import __version__ as PILLOW_VERSION

from pantaray_llm.contracts.media import (
    LlmImageProjectionRecipe,
    LlmMaterializedMediaDescriptor,
    LlmMediaDescriptor,
    LlmMediaProjection,
)
from pantaray_llm.contracts.uploaded_blob import UploadedBlob
from pantaray_llm.errors import PROXY_INVALID_INPUT, ProviderError
from pantaray_llm.providers.uploaded_content import (
    request_too_large_error,
    require_uploaded_blob,
)

IMAGE_WEBP_QUALITY = 80
IMAGE_WEBP_METHOD = 6
IMAGE_MIN_LONG_EDGE_PX = 640
IMAGE_MAX_RESIZE_ATTEMPTS = 8
IMAGE_MAX_DECODED_PIXELS_PER_REQUEST = 64_000_000
_PER_IMAGE_PIXEL_LIMIT_MESSAGE = "Image input exceeds the decoded pixel limit."
_EXIF_ORIENTATION_TAG = 0x0112
_EXIF_AXIS_SWAPPING_ORIENTATIONS = frozenset({5, 6, 7, 8})
_TRANSPOSE_BY_EXIF_ORIENTATION = {
    2: Image.Transpose.FLIP_LEFT_RIGHT,
    3: Image.Transpose.ROTATE_180,
    4: Image.Transpose.FLIP_TOP_BOTTOM,
    5: Image.Transpose.TRANSPOSE,
    6: Image.Transpose.ROTATE_270,
    7: Image.Transpose.TRANSVERSE,
    8: Image.Transpose.ROTATE_90,
}
LIBWEBP_VERSION = features.version("webp")
if not LIBWEBP_VERSION:
    raise RuntimeError("Pillow WebP support is required for LLM image projection")
IMAGE_ENCODER = f"Pillow/{PILLOW_VERSION}/libwebp-{LIBWEBP_VERSION}"
type MediaPosition = tuple[int, int]


@dataclass(frozen=True, slots=True)
class MaterializedMedia:
    payload: bytes
    mime_type: str
    width_px: int | None = None
    height_px: int | None = None


@dataclass(frozen=True, slots=True)
class RequestMedia:
    position: MediaPosition
    projection: LlmMediaProjection
    source_blob: UploadedBlob | None
    is_history: bool


@dataclass(frozen=True, slots=True)
class PreparedMedia:
    position: MediaPosition
    projection: LlmMediaProjection
    materialized: MaterializedMedia | None
    is_history: bool


@dataclass(frozen=True, slots=True)
class FittedRequest[RequestT]:
    request: RequestT
    media: tuple[PreparedMedia, ...]
    request_size_bytes: int


def original_media_projection(
    *,
    descriptor: LlmMediaDescriptor,
    source_blob: UploadedBlob,
) -> LlmMediaProjection:
    require_uploaded_blob(
        descriptor=descriptor,
        uploaded_blobs={descriptor.blob_ref: source_blob},
    )
    width_px, height_px = _source_image_shape(source_blob.payload)
    return LlmMediaProjection(
        state="inline",
        source=descriptor,
        materialized=LlmMaterializedMediaDescriptor(
            mime_type=descriptor.mime_type,
            byte_size=descriptor.byte_size,
            sha256=descriptor.sha256,
            width_px=width_px,
            height_px=height_px,
        ),
    )


def _materialize_media_projection(
    *,
    projection: LlmMediaProjection,
    source_blob: UploadedBlob | None,
) -> MaterializedMedia | None:
    if projection.state == "reference":
        return None
    if source_blob is None:
        raise _projection_error("Inline media projection source was not uploaded.")
    require_uploaded_blob(
        descriptor=projection.source,
        uploaded_blobs={projection.source.blob_ref: source_blob},
    )
    descriptor = projection.materialized
    if descriptor is None:  # pragma: no cover - schema invariant
        raise AssertionError("inline projection omitted materialized metadata")
    recipe = projection.image_recipe
    if recipe is None:
        width_px, height_px = _source_image_shape(source_blob.payload)
        materialized = MaterializedMedia(
            payload=source_blob.payload,
            mime_type=source_blob.mime_type,
            width_px=width_px,
            height_px=height_px,
        )
    else:
        if recipe.encoder != IMAGE_ENCODER:
            raise _projection_error(
                "Saved image projection requires a different encoder version."
            )
        materialized = _encode_source_image(
            payload=source_blob.payload,
            width_px=recipe.width_px,
            height_px=recipe.height_px,
            quality=recipe.quality,
            method=recipe.method,
        )
    _verify_materialized(descriptor=descriptor, materialized=materialized)
    return materialized


def fit_request_media_to_budget[RequestT](
    *,
    media: tuple[RequestMedia, ...],
    render: Callable[[tuple[PreparedMedia, ...]], RequestT],
    measure: Callable[[RequestT], int],
    max_request_bytes: int,
    min_long_edge_px: int = IMAGE_MIN_LONG_EDGE_PX,
) -> FittedRequest[RequestT]:
    if max_request_bytes <= 0:
        raise ValueError("max_request_bytes must be positive")
    if min_long_edge_px <= 0:
        raise ValueError("min_long_edge_px must be positive")

    dimensions = _admit_request_media(media)
    baseline = tuple(_materialize_request_media(item) for item in media)
    image_indexes = tuple(dimensions)
    baseline_request = render(baseline)
    baseline_size = measure(baseline_request)
    if baseline_size <= max_request_bytes:
        return FittedRequest(
            request=baseline_request,
            media=baseline,
            request_size_bytes=baseline_size,
        )

    if not image_indexes:
        raise request_too_large_error(
            request_size_bytes=baseline_size,
            max_request_bytes=max_request_bytes,
            reason="request_without_reducible_images",
        )

    best_media = baseline
    best_size = baseline_size
    scale = 1.0
    previous_targets: tuple[tuple[int, int], ...] | None = None
    for _attempt in range(IMAGE_MAX_RESIZE_ATTEMPTS):
        targets = tuple(
            _scaled_dimensions(
                width_px=dimensions[index][0],
                height_px=dimensions[index][1],
                scale=scale,
                min_long_edge_px=min_long_edge_px,
            )
            for index in image_indexes
        )
        if targets == previous_targets:
            break
        previous_targets = targets
        candidate = list(baseline)
        for index, (width_px, height_px) in zip(
            image_indexes,
            targets,
            strict=True,
        ):
            candidate[index] = _resize_request_media(
                item=media[index],
                width_px=width_px,
                height_px=height_px,
            )
        candidate_tuple = tuple(candidate)
        candidate_request = render(candidate_tuple)
        candidate_size = measure(candidate_request)
        if candidate_size < best_size:
            best_media = candidate_tuple
            best_size = candidate_size
        if candidate_size <= max_request_bytes:
            return FittedRequest(
                request=candidate_request,
                media=candidate_tuple,
                request_size_bytes=candidate_size,
            )
        scale = _next_scale(
            current_scale=scale,
            request_size_bytes=candidate_size,
            max_request_bytes=max_request_bytes,
        )

    candidate = list(best_media)
    for index, item in enumerate(candidate):
        if not _can_reference(item):
            continue
        candidate[index] = PreparedMedia(
            position=item.position,
            projection=LlmMediaProjection(
                state="reference",
                source=item.projection.source,
            ),
            materialized=None,
            is_history=True,
        )
        candidate_tuple = tuple(candidate)
        candidate_request = render(candidate_tuple)
        candidate_size = measure(candidate_request)
        if candidate_size <= max_request_bytes:
            return FittedRequest(
                request=candidate_request,
                media=candidate_tuple,
                request_size_bytes=candidate_size,
            )
        if candidate_size < best_size:
            best_media = candidate_tuple
            best_size = candidate_size

    has_current_image = any(
        not item.is_history and item.projection.state == "inline" for item in best_media
    )
    raise request_too_large_error(
        request_size_bytes=best_size,
        max_request_bytes=max_request_bytes,
        reason=("active_media_too_large" if has_current_image else "media_too_large"),
    )


def media_reference_text(projection: LlmMediaProjection) -> str:
    application_ref = projection.source.application_ref
    if projection.state != "reference" or application_ref is None:
        raise ValueError("media reference text requires a reference projection")
    return (
        "[Earlier image omitted from this request because of the provider byte "
        f"limit. Read it again with its existing reference: {application_ref}]"
    )


def has_equivalent_inline_projection(
    *,
    projection: LlmMediaProjection,
    history: Iterable[LlmMediaProjection],
) -> bool:
    return any(saved.state == "inline" and saved == projection for saved in history)


def verify_projected_media_payload(
    *,
    projection: LlmMediaProjection,
    payload: bytes,
    mime_type: str,
) -> None:
    descriptor = projection.materialized
    if projection.state != "inline" or descriptor is None:
        raise _projection_error("Media payload requires an inline projection.")
    _verify_descriptor_payload(
        descriptor=descriptor,
        payload=payload,
        mime_type=mime_type,
    )


def _verify_descriptor_payload(
    *,
    descriptor: LlmMaterializedMediaDescriptor,
    payload: bytes,
    mime_type: str,
) -> None:
    if (
        descriptor.mime_type != mime_type
        or descriptor.byte_size != len(payload)
        or descriptor.sha256 != hashlib.sha256(payload).hexdigest()
    ):
        raise _projection_error("Saved media differs from the projected request media.")


def _materialize_request_media(item: RequestMedia) -> PreparedMedia:
    return PreparedMedia(
        position=item.position,
        projection=item.projection,
        materialized=_materialize_media_projection(
            projection=item.projection,
            source_blob=item.source_blob,
        ),
        is_history=item.is_history,
    )


def _admit_request_media(
    media: tuple[RequestMedia, ...],
) -> dict[int, tuple[int, int]]:
    dimensions: dict[int, tuple[int, int]] = {}
    total_pixels = 0
    for index, item in enumerate(media):
        if item.projection.state != "inline":
            continue
        if item.source_blob is None:  # pragma: no cover - projection invariant
            raise AssertionError("inline image projection omitted its source blob")
        source_width_px, source_height_px = _source_image_shape(
            item.source_blob.payload
        )
        total_pixels += source_width_px * source_height_px
        if total_pixels > IMAGE_MAX_DECODED_PIXELS_PER_REQUEST:
            raise _invalid_image_error(
                "Image inputs exceed the aggregate decoded pixel limit."
            )
        materialized = item.projection.materialized
        if (
            materialized is None
            or materialized.width_px is None
            or materialized.height_px is None
        ):  # pragma: no cover - image projection invariant
            raise AssertionError("inline image projection omitted dimensions")
        dimensions[index] = (materialized.width_px, materialized.height_px)
    return dimensions


def _resize_request_media(
    *,
    item: RequestMedia,
    width_px: int,
    height_px: int,
) -> PreparedMedia:
    if item.source_blob is None:  # pragma: no cover - reference media is excluded
        raise AssertionError("inline projection omitted its source blob")
    materialized = _encode_source_image(
        payload=item.source_blob.payload,
        width_px=width_px,
        height_px=height_px,
        quality=IMAGE_WEBP_QUALITY,
        method=IMAGE_WEBP_METHOD,
    )
    descriptor = _materialized_descriptor(materialized)
    projection = LlmMediaProjection(
        state="inline",
        source=item.projection.source,
        materialized=descriptor,
        image_recipe=LlmImageProjectionRecipe(
            kind="webp_resize",
            width_px=width_px,
            height_px=height_px,
            quality=IMAGE_WEBP_QUALITY,
            method=IMAGE_WEBP_METHOD,
            encoder=IMAGE_ENCODER,
        ),
    )
    return PreparedMedia(
        position=item.position,
        projection=projection,
        materialized=materialized,
        is_history=item.is_history,
    )


def _can_reference(item: PreparedMedia) -> bool:
    return (
        item.is_history
        and item.projection.state == "inline"
        and item.projection.source.application_ref is not None
    )


def _scaled_dimensions(
    *,
    width_px: int,
    height_px: int,
    scale: float,
    min_long_edge_px: int,
) -> tuple[int, int]:
    long_edge = max(width_px, height_px)
    target_long_edge = max(min(long_edge, min_long_edge_px), round(long_edge * scale))
    if target_long_edge >= long_edge:
        return width_px, height_px
    ratio = target_long_edge / long_edge
    return max(1, round(width_px * ratio)), max(1, round(height_px * ratio))


def _next_scale(
    *,
    current_scale: float,
    request_size_bytes: int,
    max_request_bytes: int,
) -> float:
    estimated_factor = math.sqrt(max_request_bytes / request_size_bytes) * 0.95
    return current_scale * min(0.9, max(0.1, estimated_factor))


def _image_shape(
    opened: Image.Image, *, orientation: int | None = None
) -> tuple[int, int]:
    width_px, height_px = opened.size
    if (
        width_px <= 0
        or height_px <= 0
        or width_px * height_px > IMAGE_MAX_DECODED_PIXELS_PER_REQUEST
    ):
        raise _invalid_image_error(_PER_IMAGE_PIXEL_LIMIT_MESSAGE)
    if orientation is None:
        orientation = Image.Image.getexif(opened).get(_EXIF_ORIENTATION_TAG, 1)
    if orientation in _EXIF_AXIS_SWAPPING_ORIENTATIONS:
        return height_px, width_px
    return width_px, height_px


def _source_image_shape(payload: bytes) -> tuple[int, int]:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            # Animated inputs intentionally use frame 0, matching decode behavior.
            return _image_shape(opened)
    except Image.DecompressionBombError as exc:
        raise _invalid_image_error(_PER_IMAGE_PIXEL_LIMIT_MESSAGE) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise _invalid_image_error("Image input could not be decoded.") from exc


def _encode_source_image(
    *,
    payload: bytes,
    width_px: int,
    height_px: int,
    quality: int,
    method: int,
) -> MaterializedMedia:
    image = _decode_source_image(payload)
    resized: Image.Image | None = None
    converted: Image.Image | None = None
    try:
        if width_px > image.width or height_px > image.height:
            raise _projection_error("Saved image projection would enlarge its source.")
        working = image
        if (width_px, height_px) != image.size:
            resized = image.resize((width_px, height_px), Image.Resampling.LANCZOS)
            working = resized
        if working.mode not in {"RGB", "RGBA"}:
            converted = working.convert("RGBA" if "A" in working.getbands() else "RGB")
            working = converted
        output = io.BytesIO()
        working.save(
            output,
            format="WEBP",
            quality=quality,
            method=method,
        )
        return MaterializedMedia(
            payload=output.getvalue(),
            mime_type="image/webp",
            width_px=width_px,
            height_px=height_px,
        )
    except ProviderError:
        raise
    except (OSError, ValueError) as exc:
        raise _invalid_image_error("Image input could not be encoded.") from exc
    finally:
        if converted is not None:
            converted.close()
        if resized is not None:
            resized.close()
        image.close()


def _decode_source_image(payload: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(payload)) as opened:
            orientation = Image.Image.getexif(opened).get(_EXIF_ORIENTATION_TAG, 1)
            _image_shape(opened, orientation=orientation)
            # Ignore PNG eXIf after IDAT to keep inspection and decoding consistent.
            opened.load()
            transpose = _TRANSPOSE_BY_EXIF_ORIENTATION.get(orientation)
            if transpose is None:
                return opened.copy()
            return opened.transpose(transpose)
    except Image.DecompressionBombError as exc:
        raise _invalid_image_error(_PER_IMAGE_PIXEL_LIMIT_MESSAGE) from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise _invalid_image_error("Image input could not be decoded.") from exc


def _materialized_descriptor(
    materialized: MaterializedMedia,
) -> LlmMaterializedMediaDescriptor:
    return LlmMaterializedMediaDescriptor(
        mime_type=materialized.mime_type,
        byte_size=len(materialized.payload),
        sha256=hashlib.sha256(materialized.payload).hexdigest(),
        width_px=materialized.width_px,
        height_px=materialized.height_px,
    )


def _verify_materialized(
    *,
    descriptor: LlmMaterializedMediaDescriptor,
    materialized: MaterializedMedia,
) -> None:
    _verify_descriptor_payload(
        descriptor=descriptor,
        payload=materialized.payload,
        mime_type=materialized.mime_type,
    )
    if (
        descriptor.width_px != materialized.width_px
        or descriptor.height_px != materialized.height_px
    ):
        raise _projection_error("Saved media projection failed integrity verification.")


def _invalid_image_error(message: str) -> ProviderError:
    return ProviderError(
        status_code=400,
        code=PROXY_INVALID_INPUT,
        message=message,
        details={"reason": "invalid_image"},
    )


def _projection_error(message: str) -> ProviderError:
    return ProviderError(
        status_code=400,
        code=PROXY_INVALID_INPUT,
        message=message,
        details={"reason": "media_projection_integrity"},
    )


__all__ = [
    "FittedRequest",
    "IMAGE_MIN_LONG_EDGE_PX",
    "MaterializedMedia",
    "PreparedMedia",
    "RequestMedia",
    "fit_request_media_to_budget",
    "has_equivalent_inline_projection",
    "media_reference_text",
    "original_media_projection",
    "verify_projected_media_payload",
]
