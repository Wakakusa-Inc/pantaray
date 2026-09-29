"""Lay out a Word, PowerPoint or Excel file as a PDF the page renderer can draw.

LibreOffice does the layout, headless, in a process of its own: a fresh work
directory, a fresh profile, a short environment, the seatbelt profile in
office_convert_sandbox, and a deadline after which its whole process group is
killed. Nothing of a conversion outlives the call: the work directory, the
profile and the copy of the input are removed however the call ends.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import signal
import sys
import tempfile
from collections.abc import Mapping
from pathlib import Path
from types import MappingProxyType
from typing import Final, Literal

from .document_model import DocumentExtractionError
from .office_convert_sandbox import sandboxed_argv

OfficeFormat = Literal["docx", "pptx", "xlsx"]

# Design limit: a cold conversion measured about 3.5 s per file, so this only
# ends a conversion that has stopped making progress; raise it if real
# documents are reported as timing out.
MAX_OFFICE_CONVERT_SECONDS: Final = 60.0
# Each format's PDF export, with the options that keep a page number meaning
# what the read tool's unit number means: every slide including hidden ones, so
# slide N is page N, and one page per sheet, so a chart is never split across
# pages.
_EXPORT_FILTERS: Final[Mapping[OfficeFormat, str]] = MappingProxyType(
    {
        "docx": "pdf:writer_pdf_Export",
        "pptx": (
            "pdf:impress_pdf_Export:"
            '{"ExportHiddenSlides":{"type":"boolean","value":"true"}}'
        ),
        "xlsx": (
            'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}'
        ),
    }
)
# The parent's variables LibreOffice may use; everything else stays behind.
_INHERITED_ENVIRONMENT: Final = ("HOME", "LANG")
# _CS_DARWIN_USER_TEMP_DIR in <unistd.h>; os.confstr_names does not list it.
_CS_DARWIN_USER_TEMP_DIR: Final = 65537
# LibreOffice's stderr, as relayed by a process that was holding an untrusted
# file when it wrote it.
_MAX_REASON_CHARS: Final = 200


class OfficeDocumentUnreadableError(DocumentExtractionError):
    """LibreOffice exited without producing a PDF of the document."""


class OfficeConversionTimeoutError(DocumentExtractionError):
    """LibreOffice was still converting when its time ran out, and was killed."""


async def convert_office_to_pdf(
    *,
    libreoffice_app: Path,
    source: Path,
    document_format: OfficeFormat,
    destination: Path,
    timeout_seconds: float = MAX_OFFICE_CONVERT_SECONDS,
) -> None:
    """Convert ``source`` and leave the PDF at ``destination``.

    ``libreoffice_app`` is the resolved real path of a LibreOffice.app bundle
    the caller has already checked. ``source`` is copied before LibreOffice
    starts, so the conversion reads only its own copy. ``destination`` is
    replaced if it exists and is untouched when the conversion fails.

    Raises:
        OfficeDocumentUnreadableError: LibreOffice failed or produced no PDF.
        OfficeConversionTimeoutError: the conversion ran out of time and its
            process group was killed.
    """

    work_dir = Path(tempfile.mkdtemp(prefix="pantaray-office-", dir=_user_temp_dir()))
    try:
        for name in ("in", "out", "tmp"):
            (work_dir / name).mkdir()
        staged = work_dir / "in" / f"input.{document_format}"
        shutil.copyfile(source, staged)
        await _run_libreoffice(
            libreoffice_app=libreoffice_app,
            work_dir=work_dir,
            staged=staged,
            document_format=document_format,
            timeout_seconds=timeout_seconds,
        )
        shutil.move(work_dir / "out" / "input.pdf", destination)
    finally:
        shutil.rmtree(work_dir)


async def _run_libreoffice(
    *,
    libreoffice_app: Path,
    work_dir: Path,
    staged: Path,
    document_format: OfficeFormat,
    timeout_seconds: float,
) -> None:
    argv = (
        str(libreoffice_app / "Contents" / "MacOS" / "soffice"),
        "--headless",
        "--norestore",
        "--nologo",
        "--nolockcheck",
        # A profile of its own per conversion: the user's LibreOffice profile
        # is never touched, and concurrent conversions get separate
        # single-instance pipes instead of handing work to one another.
        f"-env:UserInstallation={(work_dir / 'profile').as_uri()}",
        "--convert-to",
        _EXPORT_FILTERS[document_format],
        "--outdir",
        str(work_dir / "out"),
        str(staged),
    )
    process = await asyncio.create_subprocess_exec(
        *sandboxed_argv(argv, libreoffice_app=libreoffice_app, work_dir=work_dir),
        cwd=work_dir,
        env=_environment(work_dir),
        stdin=asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
        # Its own process group, so a timeout ends whatever it started too.
        start_new_session=True,
    )
    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout_seconds)
    except TimeoutError as error:
        raise OfficeConversionTimeoutError(
            f"conversion did not finish within {timeout_seconds:g} seconds"
        ) from error
    finally:
        if process.returncode is None:
            # The group can empty between the deadline and the kill.
            with contextlib.suppress(ProcessLookupError):
                os.killpg(process.pid, signal.SIGKILL)
            await process.wait()
    # LibreOffice exits 0 when it cannot load a document, so the PDF itself is
    # the evidence of success.
    if process.returncode != 0 or not (work_dir / "out" / "input.pdf").is_file():
        reason = stderr.decode("utf-8", errors="replace").strip()
        raise OfficeDocumentUnreadableError(
            f"LibreOffice did not convert the document (exit status "
            f"{process.returncode}): {reason[-_MAX_REASON_CHARS:]}"
        )


def _environment(work_dir: Path) -> dict[str, str]:
    inherited = {
        name: os.environ[name] for name in _INHERITED_ENVIRONMENT if name in os.environ
    }
    return {**inherited, "PATH": "/usr/bin:/bin", "TMPDIR": str(work_dir / "tmp")}


def _user_temp_dir() -> str:
    """The per-user temporary directory, by the name seatbelt will match.

    macOS gives each user a private (0700) temporary directory; it is asked for
    directly rather than read from TMPDIR, which the helper's launcher may have
    pointed anywhere. Resolved because ``/var`` is a link to ``/private/var``.
    """

    # Keep both paths type-checked on Linux CI; mypy folds a direct sys.platform guard.
    on_macos = sys.platform == "darwin"
    if on_macos:
        user_temp_dir = os.confstr(_CS_DARWIN_USER_TEMP_DIR)
        if user_temp_dir is None:
            raise OSError("macOS reported no per-user temporary directory")
        return os.path.realpath(user_temp_dir)
    # Only the Linux unit tests come here; the app ships on macOS alone.
    return os.path.realpath(tempfile.gettempdir())


__all__ = [
    "MAX_OFFICE_CONVERT_SECONDS",
    "OfficeConversionTimeoutError",
    "OfficeDocumentUnreadableError",
    "OfficeFormat",
    "convert_office_to_pdf",
]
