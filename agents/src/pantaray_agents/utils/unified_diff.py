"""unified diff（diff -u 形式）の適用ユーティリティ。

本モジュールは、LLM が出力した unified diff をサーバ側で安全に適用し、
Storage 上の Markdown ドキュメントを部分編集するために使用する。
"""

from __future__ import annotations

import re
from dataclasses import dataclass


class UnifiedDiffError(ValueError):
    """unified diff の処理に失敗した場合の基底例外。"""


class UnifiedDiffParseError(UnifiedDiffError):
    """unified diff の構文解析に失敗した場合の例外。"""


class UnifiedDiffApplyError(UnifiedDiffError):
    """unified diff を本文へ適用できない場合（コンテキスト不一致等）の例外。"""


_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@"
)


@dataclass(frozen=True, slots=True)
class _Hunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    lines: list[str]


def apply_unified_diff(base_text: str, diff_text: str) -> str:
    """unified diff（diff -u）を `base_text` に適用して更新後の本文を返す。

    サポート範囲:
    - 単一ファイルの unified diff のみ
    - hunk（@@ ... @@）は複数対応
    - 行単位の追加/削除/置換（` ` / `+` / `-`）を厳密適用

    Args:
        base_text: 適用対象の元本文。
        diff_text: unified diff 文字列（LLM出力など）。

    Returns:
        diff 適用後の本文。

    Raises:
        UnifiedDiffParseError: diff の構文が不正な場合。
        UnifiedDiffApplyError: コンテキスト不一致などで適用できない場合。
    """
    if not diff_text or not diff_text.strip():
        raise UnifiedDiffParseError("diff_text is empty")

    # Normalize line endings for predictable matching.
    base_text = base_text.replace("\r\n", "\n").replace("\r", "\n")
    diff_text = diff_text.replace("\r\n", "\n").replace("\r", "\n")

    base_lines = base_text.split("\n")
    base_has_trailing_newline = base_text.endswith("\n")
    if base_text == "":
        base_lines = []
    if base_has_trailing_newline:
        # split("\n") produces a last empty element when text ends with newline; drop it for line-based ops
        base_lines = base_lines[:-1]

    hunks = _parse_unified_diff(diff_text)

    out_lines: list[str] = []
    base_idx = 0

    for hunk in hunks:
        # hunk.old_start is 1-based; allow 0 for create-from-empty hunks.
        target_idx = max(hunk.old_start - 1, 0)
        if target_idx < base_idx:
            raise UnifiedDiffApplyError("hunk overlaps or is out of order")

        # Copy untouched lines before the hunk.
        out_lines.extend(base_lines[base_idx:target_idx])
        base_idx = target_idx

        for raw in hunk.lines:
            if not raw:
                # Empty line still has a prefix in diff; if raw is empty here it's malformed.
                raise UnifiedDiffParseError("malformed diff line in hunk")

            tag = raw[0]
            content = raw[1:]

            if tag == " ":
                if base_idx >= len(base_lines):
                    if content == "" and base_has_trailing_newline:
                        continue
                    raise UnifiedDiffApplyError("context line exceeds base length")
                if base_lines[base_idx] != content:
                    raise UnifiedDiffApplyError("context mismatch")
                out_lines.append(base_lines[base_idx])
                base_idx += 1
            elif tag == "-":
                if base_idx >= len(base_lines):
                    raise UnifiedDiffApplyError("deletion exceeds base length")
                if base_lines[base_idx] != content:
                    raise UnifiedDiffApplyError("deletion mismatch")
                base_idx += 1
            elif tag == "+":
                out_lines.append(content)
            elif tag == "\\":
                # "\ No newline at end of file" – ignore.
                continue
            else:
                raise UnifiedDiffParseError(f"unexpected diff line prefix: {tag!r}")

    # Append remaining lines after last hunk.
    out_lines.extend(base_lines[base_idx:])

    result = "\n".join(out_lines)
    if base_has_trailing_newline:
        result += "\n"
    return result


def _parse_unified_diff(diff_text: str) -> list[_Hunk]:
    """unified diff を解析し、hunk のリストを返す（内部用）。"""
    lines = diff_text.split("\n")

    # Discard any leading/trailing empty lines around diff (LLM output safety).
    while lines and lines[0] == "":
        lines.pop(0)
    while lines and lines[-1] == "":
        lines.pop()

    # Find first hunk. We tolerate missing '---/+++' headers, but require at least one hunk.
    hunks: list[_Hunk] = []
    i = 0

    first_hunk_index = next(
        (idx for idx, ln in enumerate(lines) if _HUNK_HEADER_RE.match(ln)),
        None,
    )
    if first_hunk_index is None:
        raise UnifiedDiffParseError("no hunks found in unified diff")

    # If multiple file diffs are included before the first hunk, it is ambiguous
    # for our single-file editing. Header-like Markdown lines inside hunks are
    # normal diff lines and must not be counted as file headers.
    file_header_count = sum(
        1 for ln in lines[:first_hunk_index] if ln.startswith("--- ")
    )
    if file_header_count > 1:
        raise UnifiedDiffParseError("multiple file diffs are not supported")

    while i < len(lines):
        line = lines[i]
        m = _HUNK_HEADER_RE.match(line)
        if not m:
            i += 1
            continue

        old_start = int(m.group("old_start"))
        old_count = int(m.group("old_count") or "1")
        new_start = int(m.group("new_start"))
        new_count = int(m.group("new_count") or "1")

        i += 1
        hunk_lines: list[str] = []
        while i < len(lines):
            nxt = lines[i]
            if _HUNK_HEADER_RE.match(nxt):
                break
            if nxt.startswith("--- ") and hunk_lines:
                # Another file header inside a hunk region is invalid.
                raise UnifiedDiffParseError("unexpected file header inside hunks")
            if nxt.startswith((" ", "+", "-", "\\")):
                hunk_lines.append(nxt)
                i += 1
                continue
            # Unrecognized line inside hunk.
            raise UnifiedDiffParseError(f"invalid line in hunk: {nxt!r}")

        hunks.append(
            _Hunk(
                old_start=old_start,
                old_count=old_count,
                new_start=new_start,
                new_count=new_count,
                lines=hunk_lines,
            )
        )

    if not hunks:
        raise UnifiedDiffParseError("no hunks found in unified diff")

    return hunks
