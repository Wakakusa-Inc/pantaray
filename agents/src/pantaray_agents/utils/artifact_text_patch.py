"""Apply artifact Markdown patches through deterministic in-process appliers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pantaray_agents.utils.patch_dsl import (
    PatchDslError,
    apply_patch_dsl_to_text,
    has_patch_dsl_markers,
    is_patch_dsl,
)
from pantaray_agents.utils.unified_diff import (
    UnifiedDiffApplyError,
    UnifiedDiffError,
    UnifiedDiffParseError,
    apply_unified_diff,
)
from pantaray_agents.utils.unified_diff_scan import scan_unified_diff_header_pairs

ArtifactPatchLogicalPath = Literal["structured_facts.md", "long_term.md"]

DEFAULT_ARTIFACT_PATCH_TIMEOUT_MS = 10_000
PATCH_PATH_DEV_NULL = "/dev/null"


class ArtifactTextPatchError(RuntimeError):
    """artifact text patch processing failed."""


class ArtifactPatchFormatError(ArtifactTextPatchError):
    """The patch is not valid artifact patch input."""


class ArtifactPatchPathError(ArtifactTextPatchError):
    """The patch targets an unexpected artifact path."""


class ArtifactPatchApplyError(ArtifactTextPatchError):
    """The patch could not be applied to the artifact text."""


class ArtifactPatchCommandUnavailableError(ArtifactTextPatchError):
    """No supported patch command is available."""


class ArtifactPatchTimeoutError(ArtifactTextPatchError):
    """Patch application did not finish within the configured timeout."""


@dataclass(frozen=True, slots=True)
class ArtifactPatchTarget:
    logical_path: ArtifactPatchLogicalPath
    base_text: str


@dataclass(frozen=True, slots=True)
class ArtifactTextPatchResult:
    updated_text: str
    stdout: str
    stderr: str


@dataclass(frozen=True, slots=True)
class _PatchHeaderPair:
    old_path: str | None
    new_path: str | None
    first_line_index: int
    next_header_index: int


def apply_artifact_text_patch(
    *,
    target: ArtifactPatchTarget,
    patch_text: str,
    timeout_ms: int = DEFAULT_ARTIFACT_PATCH_TIMEOUT_MS,
) -> ArtifactTextPatchResult:
    """Apply a single-artifact patch to plaintext.

    The preferred input is the `*** Begin Patch` patch format. Legacy unified diff input
    is still applied in-process so artifact agents no longer depend on patch(1).
    """
    _validate_timeout_ms(timeout_ms)
    if is_patch_dsl(patch_text):
        try:
            result = apply_patch_dsl_to_text(
                base_text=target.base_text,
                patch_text=patch_text,
                expected_path=target.logical_path,
            )
        except PatchDslError as exc:
            raise ArtifactPatchApplyError(str(exc)) from exc
        return ArtifactTextPatchResult(
            updated_text=result.updated_text,
            stdout="",
            stderr="",
        )
    if has_patch_dsl_markers(patch_text):
        raise ArtifactPatchFormatError(
            "PATCH_DSL_ENVELOPE_ERROR: patch_text contains artifact patch DSL "
            "markers, but the envelope is malformed.\n\n"
            f"{_artifact_patch_dsl_instruction(target.logical_path)}"
        )

    patch_lines = _normalize_patch_text(
        patch_text=patch_text,
        logical_path=target.logical_path,
    )
    _validate_patch_contract(
        patch_lines=patch_lines,
        logical_path=target.logical_path,
    )
    try:
        updated_text = apply_unified_diff(target.base_text, patch_text)
    except UnifiedDiffParseError as exc:
        raise ArtifactPatchFormatError(str(exc)) from exc
    except UnifiedDiffApplyError as exc:
        raise ArtifactPatchApplyError(
            "PATCH_APPLY_REJECTED: patch could not apply to "
            f"{target.logical_path}.\n\n{exc}\n\n"
            f"{_artifact_patch_dsl_instruction(target.logical_path)}"
        ) from exc
    except UnifiedDiffError as exc:
        raise ArtifactPatchApplyError(str(exc)) from exc
    if (
        updated_text
        and not updated_text.endswith("\n")
        and "\\ No newline at end of file" not in patch_text
        and any(
            line.startswith("+") and not line.startswith("+++") for line in patch_lines
        )
    ):
        updated_text += "\n"
    return ArtifactTextPatchResult(
        updated_text=updated_text,
        stdout="",
        stderr="",
    )


def _validate_timeout_ms(timeout_ms: int) -> None:
    if timeout_ms <= 0:
        raise ValueError("timeout_ms must be positive")


def _normalize_patch_text(
    *,
    patch_text: str,
    logical_path: ArtifactPatchLogicalPath,
) -> list[str]:
    normalized = patch_text.replace("\r\n", "\n").replace("\r", "\n")
    if not normalized.strip():
        raise ArtifactPatchFormatError(
            "PATCH_FORMAT_EMPTY: patch_text is empty. "
            f"{_artifact_patch_dsl_instruction(logical_path)}"
        )
    return normalized.split("\n")


def _validate_patch_contract(
    *,
    patch_lines: list[str],
    logical_path: ArtifactPatchLogicalPath,
) -> _PatchHeaderPair:
    header_pairs = _extract_header_pairs(patch_lines)
    if not header_pairs:
        raise ArtifactPatchFormatError(
            "PATCH_FORMAT_MISSING_HEADER: patch_text must use the artifact patch "
            "DSL for the target artifact.\n\n"
            f"{_artifact_patch_dsl_instruction(logical_path)}"
        )
    if len(header_pairs) > 1:
        raise ArtifactPatchPathError(
            "PATCH_PATH_MULTIPLE_FILES: artifact patches must target exactly one "
            f"file: {logical_path}."
        )
    header_pair = header_pairs[0]
    hunk_lines = patch_lines[
        header_pair.first_line_index + 2 : header_pair.next_header_index
    ]
    if not any(line.startswith("@@ ") for line in hunk_lines):
        raise ArtifactPatchFormatError(
            "PATCH_FORMAT_MISSING_HUNK: patch_text must include at least one '@@' "
            "chunk. Use unchanged context lines prefixed with a space, removed "
            "lines prefixed with '-', and added lines prefixed with '+'.\n\n"
            f"{_artifact_patch_dsl_instruction(logical_path)}"
        )

    _validate_header_path(path=header_pair.old_path, logical_path=logical_path)
    _validate_header_path(path=header_pair.new_path, logical_path=logical_path)
    return header_pair


def _extract_header_pairs(patch_lines: list[str]) -> list[_PatchHeaderPair]:
    return [
        _PatchHeaderPair(
            old_path=_normalize_header_path(pair.old_header),
            new_path=_normalize_header_path(pair.new_header),
            first_line_index=pair.first_line_index,
            next_header_index=pair.next_header_index,
        )
        for pair in scan_unified_diff_header_pairs(patch_lines)
    ]


def _normalize_header_path(raw_path: str) -> str | None:
    path = raw_path.strip().split("\t", 1)[0]
    if not path or path == PATCH_PATH_DEV_NULL:
        return None
    if path.startswith("a/") or path.startswith("b/"):
        path = path[2:]
    return path


def _validate_header_path(
    *,
    path: str | None,
    logical_path: ArtifactPatchLogicalPath,
) -> None:
    if path is None:
        raise ArtifactPatchPathError(
            "PATCH_PATH_DEV_NULL_UNSUPPORTED: artifact patches must update the "
            "existing artifact file only.\n\n"
            f"{_artifact_patch_dsl_instruction(logical_path)}"
        )
    if path != logical_path:
        raise ArtifactPatchPathError(
            "PATCH_PATH_MISMATCH: artifact patch targets "
            f"{path!r}, but this agent only accepts {logical_path!r}. "
            f"{_artifact_patch_dsl_instruction(logical_path)}"
        )
    if Path(path).is_absolute() or ".." in Path(path).parts:
        raise ArtifactPatchPathError(
            "PATCH_PATH_UNSAFE: artifact patch paths must be relative artifact "
            f"paths without '..'. Use {logical_path!r}."
        )


def _artifact_patch_dsl_instruction(logical_path: str) -> str:
    return (
        "Use this exact artifact patch DSL:\n"
        f"*** Begin Patch\n*** Update File: {logical_path}\n@@\n"
        " unchanged context line\n-old line\n+new line\n*** End Patch\n"
        "Do not use --- / +++ unified diff headers."
    )


__all__ = [
    "ArtifactPatchApplyError",
    "ArtifactPatchCommandUnavailableError",
    "ArtifactPatchFormatError",
    "ArtifactPatchLogicalPath",
    "ArtifactPatchPathError",
    "ArtifactPatchTarget",
    "ArtifactPatchTimeoutError",
    "ArtifactTextPatchError",
    "ArtifactTextPatchResult",
    "apply_artifact_text_patch",
]
