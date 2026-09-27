"""Render a .ipynb notebook as one section per cell, using the standard library.

A notebook is JSON, so reading it as a text file spends the read on escaping and
on base64 image data rather than on the code and what it produced. Here each
cell becomes a section: its source, then the outputs Jupyter stored beside it,
with images listed rather than written into the text.

nbformat is not used. It validates a notebook against a JSON schema and brings
jsonschema and traitlets along to do it, and none of that is needed to read one.
The file is untrusted instead of validated, so every shape read here is checked
where it is read, and a shape nbformat 4 does not define makes the whole
notebook unreadable rather than quietly dropping a cell from what is returned.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from typing import BinaryIO, Final

from pantaray_llm.contracts.json_value import JSONValue

from .document_model import (
    MAX_NOTEBOOK_OUTPUT_CHARS,
    DocumentExtractionError,
    DocumentImage,
    DocumentTextBudget,
    ExtractedDocument,
    resolve_start_unit,
)

_NBFORMAT_MAJOR: Final = 4
# ECMA-48 CSI sequences: IPython colours a traceback with them and tqdm redraws
# a progress bar with them, and neither is content the model should read.
_ANSI_ESCAPE: Final = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_MARKDOWN_HEADING: Final = re.compile(r"#{1,6}\s")
_MARKDOWN_FENCES: Final = ("```", "~~~")
# A kernel's language name is untrusted text that would otherwise close the
# fence it opens, so only a plain identifier is written into one.
_FENCE_LANGUAGE: Final = re.compile(r"[A-Za-z0-9_+#-]+\Z")
_PLAIN_FENCE: Final = "```"
_IMAGE_MIME_PREFIX: Final = "image/"
_PDF_MIME: Final = "application/pdf"
# Markdown before plain text: it is written to be read, where text/plain is a
# repr. An HTML rendering is never taken; a frame's HTML is thousands of tags
# and the same frame always carries a plain repr beside it.
_TEXT_MIMES: Final = ("text/markdown", "text/plain")
_DATA_OUTPUT_TYPES: Final = ("execute_result", "display_data")
# Each note stands alone and stays short, because the read tool's summary caps
# how long a single note may be and silently shortens one that runs past it.
_IPYNB_NOTES: Final = (
    "Outputs are what the notebook stored when it was last saved, not the "
    "result of running this code now. An execution count is the order of some "
    "past session, which need not match the order the cells are written in.",
    "Notebook, cell and output metadata, widget state, and cell attachments "
    "other than images are not included. An image or PDF is listed beside this "
    "text rather than rendered into it.",
    "Where an output carries markdown or plain text, that is what is shown "
    "here; an HTML rendering of the same value is not included.",
)


@dataclass(frozen=True, slots=True)
class _RenderedOutput:
    """One stored output as text, plus what rendering it had to leave behind."""

    lines: tuple[str, ...] = ()
    images: tuple[DocumentImage, ...] = ()
    dropped: int = 0
    unknown: int = 0
    cut: int = 0


def extract_ipynb(source: BinaryIO, start_unit: int | None) -> ExtractedDocument:
    notebook = _notebook_object(source.read())
    cells = _cells(notebook)
    fence = _code_fence(notebook)
    start = resolve_start_unit(start_unit, total_units=len(cells), unit_kind="cell")
    budget = DocumentTextBudget(
        unit_kind="cell", total_units=len(cells), start_unit=start
    )
    outline: list[str] = []
    images: list[DocumentImage] = []
    dropped = 0
    unknown = 0
    cut = 0
    for number, cell in enumerate(cells[start - 1 :], start=start):
        cell_type = _string(cell.get("cell_type"), "cell_type")
        source_text = _multiline_string(cell.get("source"), "source")
        lines = list(_source_lines(source_text, cell_type=cell_type, fence=fence))
        if cell_type == "markdown":
            outline.extend(_markdown_headings(source_text, number))
        attached, attached_dropped = _attachment_images(cell, number)
        images.extend(attached)
        dropped += attached_dropped
        for index, output in enumerate(_outputs(cell), start=1):
            rendered = _rendered_output(output, cell_number=number, output_number=index)
            lines.extend(rendered.lines)
            images.extend(rendered.images)
            dropped += rendered.dropped
            unknown += rendered.unknown
            cut += rendered.cut
        # A cell the budget cannot hold ends this read; total_units still counts
        # every cell, and next_start_unit says where the rest of them begin.
        if not budget.add_unit(
            number, _cell_heading(cell, number, cell_type), *lines, ""
        ):
            break
    return ExtractedDocument(
        document_format="ipynb",
        unit_kind="cell",
        total_units=len(cells),
        text=budget.finish(),
        content_truncated=budget.stopped or cut > 0,
        next_start_unit=budget.next_start_unit,
        outline=tuple(outline),
        images=tuple(images),
        notes=(
            *_IPYNB_NOTES,
            *_left_out_notes(dropped=dropped, unknown=unknown, cut=cut),
            *budget.notes(),
        ),
    )


def _notebook_object(payload: bytes) -> Mapping[str, JSONValue]:
    """The file's JSON, proved to be an nbformat 4 notebook before it is read.

    A malformed document is the caller's to report: both a decoding failure and
    a JSON syntax error are ValueErrors, which is how every other extractor's
    unusable input already reaches the read tool.
    """

    try:
        # The notebook format is UTF-8; an editor on Windows may add a BOM.
        parsed: JSONValue = json.loads(payload.decode("utf-8-sig"))
    except RecursionError as exc:
        # json's scanner refuses nesting deeper than the interpreter's recursion
        # limit by raising, so the read ends here rather than in the harness.
        raise DocumentExtractionError(
            "notebook JSON is nested too deeply to read"
        ) from exc
    if not isinstance(parsed, dict):
        raise DocumentExtractionError("notebook JSON is not an object")
    version = parsed.get("nbformat")
    if version != _NBFORMAT_MAJOR:
        raise DocumentExtractionError(
            f"notebook is nbformat {version!r}; this tool reads nbformat "
            f"{_NBFORMAT_MAJOR}"
        )
    return parsed


def _cells(notebook: Mapping[str, JSONValue]) -> tuple[Mapping[str, JSONValue], ...]:
    cells = notebook.get("cells")
    if not isinstance(cells, list):
        raise DocumentExtractionError("notebook has no cells array")
    checked: list[Mapping[str, JSONValue]] = []
    for cell in cells:
        if not isinstance(cell, dict):
            raise DocumentExtractionError("notebook has a cell that is not an object")
        checked.append(cell)
    return tuple(checked)


def _code_fence(notebook: Mapping[str, JSONValue]) -> str:
    """A fence naming the kernel's language, so code is not read as its output."""

    metadata = notebook.get("metadata")
    if not isinstance(metadata, dict):
        return _PLAIN_FENCE
    kernelspec = metadata.get("kernelspec")
    language = kernelspec.get("language") if isinstance(kernelspec, dict) else None
    if not isinstance(language, str):
        info = metadata.get("language_info")
        language = info.get("name") if isinstance(info, dict) else None
    if isinstance(language, str) and _FENCE_LANGUAGE.match(language):
        return f"{_PLAIN_FENCE}{language}"
    return _PLAIN_FENCE


def _cell_heading(cell: Mapping[str, JSONValue], number: int, cell_type: str) -> str:
    """The cell's number and kind, with the execution count Jupyter shows.

    The count is a label rather than content, so one written in a shape nbformat
    does not define is left off instead of making the notebook unreadable.
    """

    count = cell.get("execution_count")
    marker = f", In[{count}]" if isinstance(count, int) else ""
    return f"## Cell {number} ({cell_type}{marker})"


def _source_lines(source: str, *, cell_type: str, fence: str) -> Iterator[str]:
    """A cell's source, fenced when it is code so output cannot read as code."""

    lines = source.splitlines()
    if cell_type != "code" or not lines:
        yield from lines
        return
    yield fence
    yield from lines
    yield _PLAIN_FENCE


def _markdown_headings(source: str, number: int) -> Iterator[str]:
    """Heading lines, skipping the fenced code a `#` comment also starts."""

    fence = ""
    for line in source.splitlines():
        stripped = line.rstrip()
        if fence:
            if stripped.startswith(fence):
                fence = ""
        elif stripped.startswith(_MARKDOWN_FENCES):
            fence = stripped[:3]
        elif _MARKDOWN_HEADING.match(line):
            yield f"Cell {number}: {' '.join(line.split())}"


def _outputs(cell: Mapping[str, JSONValue]) -> tuple[JSONValue, ...]:
    outputs = cell.get("outputs")
    if outputs is None:
        return ()
    if not isinstance(outputs, list):
        raise DocumentExtractionError("a cell's outputs are not an array")
    return tuple(outputs)


def _rendered_output(
    output: JSONValue, *, cell_number: int, output_number: int
) -> _RenderedOutput:
    if not isinstance(output, dict):
        raise DocumentExtractionError("a cell has an output that is not an object")
    output_type = _string(output.get("output_type"), "output_type")
    if output_type == "stream":
        name = _string(output.get("name"), "stream name")
        text = _multiline_string(output.get("text"), "stream text")
        return _body(f"{name}:", text)
    if output_type in _DATA_OUTPUT_TYPES:
        return _data_output(
            output,
            label=(
                _result_label(output) if output_type == "execute_result" else "Display:"
            ),
            location=f"cell {cell_number}",
            ref=f"cell {cell_number} output {output_number}",
        )
    if output_type == "error":
        return _error_output(output)
    return _RenderedOutput(unknown=1)


def _data_output(
    output: Mapping[str, JSONValue], *, label: str, location: str, ref: str
) -> _RenderedOutput:
    """A value Jupyter stored in several representations, rendered as one."""

    data = output.get("data")
    if not isinstance(data, dict):
        raise DocumentExtractionError("an output's data is not an object")
    shown = next((mime for mime in _TEXT_MIMES if mime in data), "")
    images, dropped = _bundle_images(data, location=location, ref=ref, shown=shown)
    body = (
        _body(label, _multiline_string(data[shown], shown))
        if shown
        else _RenderedOutput()
    )
    return _RenderedOutput(
        lines=body.lines,
        images=images,
        dropped=dropped,
        cut=body.cut,
    )


def _error_output(output: Mapping[str, JSONValue]) -> _RenderedOutput:
    ename = _string(output.get("ename"), "error ename")
    evalue = _string(output.get("evalue"), "error evalue")
    traceback = output.get("traceback")
    if not isinstance(traceback, list):
        raise DocumentExtractionError("an error output's traceback is not an array")
    frames = "\n".join(_string(frame, "traceback frame") for frame in traceback)
    return _body(f"Error: {ename}: {evalue}", frames)


def _body(label: str, text: str) -> _RenderedOutput:
    """One output under its label, cut so a single output cannot flood the page."""

    clean = _ANSI_ESCAPE.sub("", text)
    cut = len(clean) > MAX_NOTEBOOK_OUTPUT_CHARS
    lines = (
        clean[:MAX_NOTEBOOK_OUTPUT_CHARS].splitlines() if cut else clean.splitlines()
    )
    if cut:
        lines.append(f"[output cut at {MAX_NOTEBOOK_OUTPUT_CHARS} characters]")
    return _RenderedOutput(lines=(label, *lines), cut=int(cut))


def _attachment_images(
    cell: Mapping[str, JSONValue], number: int
) -> tuple[tuple[DocumentImage, ...], int]:
    """Images a markdown cell carries inline, which its text references by name."""

    attachments = cell.get("attachments")
    if attachments is None:
        return (), 0
    if not isinstance(attachments, dict):
        raise DocumentExtractionError("a cell's attachments are not an object")
    images: list[DocumentImage] = []
    dropped = 0
    for name, bundle in attachments.items():
        if not isinstance(bundle, dict):
            raise DocumentExtractionError("a cell attachment is not an object")
        found, skipped = _bundle_images(
            bundle,
            location=f"cell {number}",
            ref=f"cell {number} attachment {name}",
            shown="",
        )
        images.extend(found)
        dropped += skipped
    return tuple(images), dropped


def _bundle_images(
    bundle: Mapping[str, JSONValue], *, location: str, ref: str, shown: str
) -> tuple[tuple[DocumentImage, ...], int]:
    """Split a MIME bundle into what a later tool can render and what is lost.

    Every representation is addressed by ``ref`` plus its own media type, which
    is what identifies the exact bytes inside the notebook. A representation the
    read cannot show and a renderer cannot use is only counted.
    """

    images: list[DocumentImage] = []
    dropped = 0
    for mime in bundle:
        if mime == shown:
            continue
        if mime.startswith(_IMAGE_MIME_PREFIX) or mime == _PDF_MIME:
            images.append(
                DocumentImage(location=location, ref=f"{ref} {mime}", count=1)
            )
        else:
            dropped += 1
    return tuple(images), dropped


def _result_label(output: Mapping[str, JSONValue]) -> str:
    count = output.get("execution_count")
    return f"Out[{count}]:" if isinstance(count, int) else "Out:"


def _left_out_notes(*, dropped: int, unknown: int, cut: int) -> Iterator[str]:
    if dropped:
        yield (
            f"{dropped} output representations are not shown because this tool "
            "renders only markdown and plain text; the images and PDFs among "
            "them are listed beside the text."
        )
    if unknown:
        yield (
            f"{unknown} outputs use a type this tool does not know and are not shown."
        )
    if cut:
        yield (
            f"{cut} outputs were longer than {MAX_NOTEBOOK_OUTPUT_CHARS} "
            "characters and are cut where the text says so."
        )


def _string(value: JSONValue, field: str) -> str:
    if not isinstance(value, str):
        raise DocumentExtractionError(f"notebook {field} is not a string")
    return value


def _multiline_string(value: JSONValue, field: str) -> str:
    """nbformat writes text either whole or as the list of lines it splits into."""

    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "".join(_string(line, field) for line in value)
    raise DocumentExtractionError(f"notebook {field} is not text")


__all__ = ["extract_ipynb"]
