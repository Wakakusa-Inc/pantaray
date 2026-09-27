"""Markdown文字列から特定の見出しセクションを抽出するユーティリティ。

設計意図:
- DB本文への LIKE 依存を避けるため、Storage 上の `long_term.md` 等を読み、
  そこから必要なセクション（例: "Ongoing And Past Initiatives and Projects"）だけを
  抽出してプロンプトに投入できるようにする。
- 抽出ロジックは副作用を持たない純粋関数として切り出し、ユニットテストで固定する。
"""

from __future__ import annotations

import re

_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")


def extract_markdown_section(*, markdown: str, heading_text: str) -> str:
    """Markdown本文から、指定見出しのセクションを抽出して返す。

    仕様:
    - 見出しは Markdown の ATX 見出し（`#`〜`######`）を対象とする。
    - `heading_text` は見出し行のテキスト部分と一致（前後空白は無視、大小は無視）したらヒット。
    - ヒットした見出し行を含め、次に登場する「同レベル以上（#の数が同じ or 少ない）」の見出し直前までを返す。
      （下位見出しはセクション内として含める）
    - 同名見出しが複数ある場合は **最初の一致** を採用する。
    - 見つからない場合は空文字を返す。

    Args:
        markdown: Markdown本文（UTF-8想定）。
        heading_text: 抽出対象の見出しテキスト（例: "Ongoing And Past Initiatives and Projects"）。

    Returns:
        抽出されたセクション文字列。見つからない場合は ""。
    """
    if not markdown or not heading_text:
        return ""

    lines = markdown.splitlines()
    target = heading_text.strip().casefold()

    start_idx: int | None = None
    start_level: int | None = None

    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        text = m.group(2).strip().casefold()
        if text == target:
            start_idx = i
            start_level = level
            break

    if start_idx is None or start_level is None:
        return ""

    end_idx = len(lines)
    for j in range(start_idx + 1, len(lines)):
        m = _HEADING_RE.match(lines[j])
        if not m:
            continue
        level = len(m.group(1))
        # 同レベル以上でセクション終了
        if level <= start_level:
            end_idx = j
            break

    section_lines = lines[start_idx:end_idx]
    return "\n".join(section_lines).strip()
