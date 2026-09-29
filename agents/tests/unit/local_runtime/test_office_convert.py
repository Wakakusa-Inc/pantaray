"""Converting an Office file with a LibreOffice that leaves nothing behind.

The LibreOffice here is a fake bundle whose soffice is a shell script, run
without the seatbelt profile: the profile allows executing only the bundle, and
a script's interpreter (/bin/sh) is a separate exec it rightly refuses, while a
copy of a system shell placed inside the bundle is killed by macOS for leaving
its signed location. The profile itself is pinned in
test_office_convert_sandbox, and the opt-in integration test converts real
documents through it.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import signal
from pathlib import Path

import pytest

from pantaray_agents.local_runtime.tooling.documents import office_convert
from pantaray_agents.local_runtime.tooling.documents.office_convert import (
    OfficeConversionTimeoutError,
    OfficeDocumentUnreadableError,
    OfficeFormat,
    convert_office_to_pdf,
)

# The script's arguments, parsed the way soffice is called: --outdir takes a
# value, and the document is the last argument.
_PARSE_ARGUMENTS = """\
outdir=
input=
arguments=
while [ $# -gt 0 ]; do
  arguments="$arguments$1
"
  case "$1" in
    --outdir) outdir="$2"; arguments="$arguments$2
"; shift ;;
    *) input="$1" ;;
  esac
  shift
done
"""
# How long a process group takes to be reaped once it has been killed.
_REAP_SECONDS = 5.0


@pytest.fixture(autouse=True)
def _unsandboxed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        office_convert,
        "sandboxed_argv",
        lambda argv, **_: tuple(argv),
    )


def fake_libreoffice(tmp_path: Path, body: str) -> Path:
    app = tmp_path / "LibreOffice.app"
    macos = app / "Contents" / "MacOS"
    macos.mkdir(parents=True)
    soffice = macos / "soffice"
    soffice.write_text(f"#!/bin/sh\n{_PARSE_ARGUMENTS}{body}", encoding="utf-8")
    soffice.chmod(0o755)
    return app


def write_source(tmp_path: Path) -> Path:
    source = tmp_path / "Quarterly report.docx"
    source.write_bytes(b"PK\x03\x04 not really a docx")
    return source


async def convert(
    app: Path,
    source: Path,
    destination: Path,
    *,
    document_format: OfficeFormat = "docx",
    timeout_seconds: float = office_convert.MAX_OFFICE_CONVERT_SECONDS,
) -> None:
    await convert_office_to_pdf(
        libreoffice_app=app,
        source=source,
        document_format=document_format,
        destination=destination,
        timeout_seconds=timeout_seconds,
    )


@pytest.mark.parametrize(
    ("document_format", "export_filter"),
    [
        ("docx", "pdf:writer_pdf_Export"),
        (
            "pptx",
            'pdf:impress_pdf_Export:{"ExportHiddenSlides":{"type":"boolean","value":"true"}}',
        ),
        (
            "xlsx",
            'pdf:calc_pdf_Export:{"SinglePageSheets":{"type":"boolean","value":"true"}}',
        ),
    ],
)
async def test_the_pdf_lands_at_the_destination_from_a_copy_of_the_source(
    tmp_path: Path, document_format: OfficeFormat, export_filter: str
) -> None:
    """Each format uses the export that keeps page N meaning read's unit N."""

    app = fake_libreoffice(
        tmp_path,
        '[ -f "$input" ] || exit 3\n'
        'printf "%%PDF-1.7\\n%s" "$arguments" > "$outdir/input.pdf"\n',
    )
    destination = tmp_path / "rendered.pdf"

    await convert(
        app, write_source(tmp_path), destination, document_format=document_format
    )

    arguments = destination.read_text(encoding="utf-8").splitlines()
    assert arguments[0] == "%PDF-1.7"
    assert arguments[arguments.index("--convert-to") + 1] == export_filter
    staged = Path(arguments[-1])
    assert staged.name == f"input.{document_format}"
    profile = next(a for a in arguments if a.startswith("-env:UserInstallation="))
    assert profile == (
        f"-env:UserInstallation={(staged.parent.parent / 'profile').as_uri()}"
    )
    assert not staged.parent.parent.exists()


async def test_libreoffice_sees_only_the_allowlisted_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PANTARAY_TEST_SECRET", "do-not-pass")
    monkeypatch.setenv("LANG", "ja_JP.UTF-8")
    app = fake_libreoffice(
        tmp_path,
        'printf "%%PDF-1.7\\n" > "$outdir/input.pdf"\n'
        'export -p >> "$outdir/input.pdf"\n'
        'printf "cwd=%s\\n" "$(pwd)" >> "$outdir/input.pdf"\n',
    )
    destination = tmp_path / "rendered.pdf"

    await convert(app, write_source(tmp_path), destination)

    report = destination.read_text(encoding="utf-8")
    assert "PANTARAY_TEST_SECRET" not in report
    assert "LANG='ja_JP.UTF-8'" in report or 'LANG="ja_JP.UTF-8"' in report
    assert "PATH='/usr/bin:/bin'" in report or 'PATH="/usr/bin:/bin"' in report
    work_dir = report.split("cwd=")[1].strip()
    assert f"TMPDIR='{work_dir}/tmp'" in report or f'TMPDIR="{work_dir}/tmp"' in report


@pytest.mark.parametrize("exit_status", [0, 1])
async def test_no_pdf_is_an_unreadable_document_whatever_the_exit_status(
    tmp_path: Path, exit_status: int
) -> None:
    """LibreOffice exits 0 when it cannot load a document at all."""

    cwd_file = tmp_path / "cwd"
    app = fake_libreoffice(
        tmp_path,
        f'pwd > "{cwd_file}"\n'
        'echo "Error: source file could not be loaded" >&2\n'
        f"exit {exit_status}\n",
    )
    destination = tmp_path / "rendered.pdf"

    with pytest.raises(
        OfficeDocumentUnreadableError, match="source file could not be loaded"
    ):
        await convert(app, write_source(tmp_path), destination)

    assert not destination.exists()
    assert not Path(cwd_file.read_text(encoding="utf-8").strip()).exists()


async def test_a_conversion_past_its_time_is_killed_with_everything_it_started(
    tmp_path: Path,
) -> None:
    pid_file = tmp_path / "pids"
    app = fake_libreoffice(
        tmp_path,
        # Its own streams, so a child the kill missed is caught by the check
        # below rather than holding the stderr pipe open and hanging the call.
        "( while :; do :; done ) </dev/null >/dev/null 2>&1 &\n"
        f'printf "%s %s\\n" "$!" "$(pwd)" > "{pid_file}"\n'
        "wait\n",
    )

    with pytest.raises(OfficeConversionTimeoutError):
        await convert(
            app, write_source(tmp_path), tmp_path / "rendered.pdf", timeout_seconds=1
        )

    child_pid, work_dir = pid_file.read_text(encoding="utf-8").split()
    try:
        assert not Path(work_dir).exists()
        assert await _reaped(int(child_pid))
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.kill(int(child_pid), signal.SIGKILL)


async def _reaped(pid: int) -> bool:
    """Whether ``pid`` is gone within the time a killed orphan takes to be reaped."""

    loop = asyncio.get_running_loop()
    deadline = loop.time() + _REAP_SECONDS
    while loop.time() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        await asyncio.sleep(0.05)
    return False
