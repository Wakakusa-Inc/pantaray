"""Draw PDF pages as images, in a process that is allowed to die.

This file is run as a script -- ``python -I -B <this file>`` -- rather than
imported, and it is the only place ``pypdfium2``, and through it PDFium, is
ever loaded. Running it as a script instead of ``-m`` is what keeps the process
small: as a script it imports pypdfium2, Pillow and the standard library in
about 10 ms, where importing the package this file sits in costs 1.3 s and
pulls in the whole local runtime. For the same reason nothing here imports a
sibling module, and everything this worker and its parent agree on travels in
the request.

One request on stdin, one reply on stdout, then exit. The reply is a single
JSON line followed by the pages' bytes in the order the header lists them, so
the parent never has to trust a length this process did not declare. No reply
carries a pathname: the parent already knows which file it asked about, and
this is the process holding the untrusted one.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from io import BytesIO
from typing import Final

import pypdfium2

# The encoder settings the LLM layer re-encodes an image with, in
# pantaray_llm.providers.media_projection, so a page that reaches a provider
# untouched and one that is resized on the way there look alike. The page size
# itself is the parent's decision and arrives with the request.
_WEBP_QUALITY: Final = 80
_WEBP_METHOD: Final = 6
# PDFium's own message for a document it will not open. It names the error, not
# the file, but it is still text from the process holding untrusted input, so
# the parent is handed a bounded amount of it.
_MAX_REASON_CHARS: Final = 200


@dataclass(frozen=True, slots=True)
class _DrawnPage:
    width_px: int
    height_px: int
    payload: bytes


def main() -> int:
    request = json.loads(sys.stdin.readline())
    path = str(request["path"])
    pages = [int(number) for number in request["pages"]]
    long_edge_px = int(request["long_edge_px"])
    try:
        document = pypdfium2.PdfDocument(path)
    except pypdfium2.PdfiumError as error:
        _emit(_failure(error))
        return 0
    try:
        total_units = len(document)
        beyond = next(
            (number for number in pages if not 1 <= number <= total_units), None
        )
        if beyond is not None:
            _emit(
                {
                    "status": "page_out_of_range",
                    "number": beyond,
                    "total_units": total_units,
                }
            )
            return 0
        drawn = [_draw(document[number - 1], long_edge_px) for number in pages]
    except pypdfium2.PdfiumError as error:
        _emit(_failure(error))
        return 0
    finally:
        document.close()
    _emit(
        {
            "status": "rendered",
            "total_units": total_units,
            "pages": [
                {
                    "number": number,
                    "width_px": page.width_px,
                    "height_px": page.height_px,
                    "byte_size": len(page.payload),
                }
                for number, page in zip(pages, drawn, strict=True)
            ],
        }
    )
    for page in drawn:
        sys.stdout.buffer.write(page.payload)
    sys.stdout.buffer.flush()
    return 0


def _draw(page: pypdfium2.PdfPage, long_edge_px: int) -> _DrawnPage:
    """One page, drawn to fit ``long_edge_px`` and encoded as WebP.

    A PDF page is measured in points rather than pixels, so the scale comes
    from the page's own size and both orientations land on the same long edge.
    """

    width_pt, height_pt = page.get_size()
    bitmap = page.render(scale=long_edge_px / max(width_pt, height_pt))
    try:
        # PDFium draws onto an opaque white background, so the alpha channel
        # the bitmap carries holds nothing and only costs bytes.
        image = bitmap.to_pil().convert("RGB")
    finally:
        bitmap.close()
    encoded = BytesIO()
    image.save(encoded, format="WEBP", quality=_WEBP_QUALITY, method=_WEBP_METHOD)
    return _DrawnPage(
        width_px=image.width, height_px=image.height, payload=encoded.getvalue()
    )


def _failure(error: pypdfium2.PdfiumError) -> dict[str, str]:
    """A document PDFium refused, told apart by what it refused it for.

    A PDF whose owner password only restricts printing or editing opens with an
    empty user password, which PDFium tries on its own; only one that is meant
    to be unreadable without a password reaches the password branch here.
    """

    if error.err_code == pypdfium2.raw.FPDF_ERR_PASSWORD:
        return {"status": "password_required"}
    return {"status": "unreadable", "reason": str(error)[:_MAX_REASON_CHARS]}


def _emit(reply: object) -> None:
    sys.stdout.buffer.write(json.dumps(reply).encode("utf-8") + b"\n")
    sys.stdout.buffer.flush()


if __name__ == "__main__":
    raise SystemExit(main())
