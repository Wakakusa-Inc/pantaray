"""Canonical opaque cursors for strict typed payloads."""

import base64
import binascii

from pydantic import TypeAdapter, ValidationError


class OpaqueCursorError(ValueError):
    """The cursor is malformed, non-canonical, or violates its payload contract."""


def encode_opaque_cursor[PayloadT](
    payload: PayloadT,
    *,
    adapter: TypeAdapter[PayloadT],
) -> str:
    return base64.urlsafe_b64encode(adapter.dump_json(payload)).rstrip(b"=").decode()


def decode_opaque_cursor[PayloadT](
    value: str,
    *,
    adapter: TypeAdapter[PayloadT],
) -> PayloadT:
    try:
        encoded = value.encode("ascii")
        payload_json = base64.b64decode(
            encoded + b"=" * (-len(encoded) % 4),
            altchars=b"-_",
            validate=True,
        )
        payload = adapter.validate_json(payload_json, strict=True)
    except (UnicodeEncodeError, binascii.Error, ValidationError) as error:
        raise OpaqueCursorError("cursor is malformed or non-canonical") from error
    if encode_opaque_cursor(payload, adapter=adapter) != value:
        raise OpaqueCursorError("cursor is malformed or non-canonical")
    return payload
