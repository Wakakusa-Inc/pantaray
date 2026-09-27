"""JSON 抽出ユーティリティ。

LLM の出力は「コードフェンス」「前置き/後置き」「タグ混入」などにより、
そのまま `json.loads` できないことがある。

このモジュールは、入力文字列から最初に成立する JSON オブジェクト（`{...}`）を
best-effort で抽出するための関数を提供する。
"""

from __future__ import annotations

import json


def extract_first_json_object(text: str) -> str | None:
    """文字列から最初に成立する JSON オブジェクト（`{...}`）を抽出する。

    仕様:
        - `<thinking>`/`<answer>` 等のタグは特別扱いせず、単なる文字列として扱う。
        - 先頭がコードフェンス（```）の場合は fence 行を除去してから解析する。
        - 文字列リテラル内の `{`/`}` は深さカウント対象から除外する。

    Args:
        text: 入力テキスト

    Returns:
        JSONオブジェクトとして `json.loads` 可能な文字列。見つからない場合は None。
    """

    if not text:
        return None

    candidate_text = text.strip()
    if not candidate_text:
        return None

    # コードフェンスがある場合、フェンス行を取り除く（言語指定の有無は問わない）。
    if candidate_text.startswith("```"):
        lines: list[str] = []
        for line in candidate_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("```"):
                continue
            lines.append(line)
        candidate_text = "\n".join(lines).strip()
        if not candidate_text:
            return None

    def _try_load(candidate: str) -> str | None:
        try:
            json.loads(candidate)
        except json.JSONDecodeError:
            return None
        return candidate

    direct = _try_load(candidate_text)
    if direct is not None:
        return direct

    depth = 0
    in_string = False
    escape = False
    start_index: int | None = None

    for index, char in enumerate(candidate_text):
        if escape:
            escape = False
            continue
        if char == "\\":
            if in_string:
                escape = True
            continue
        if char == '"':
            in_string = not in_string
            continue
        if in_string:
            continue

        if char == "{":
            if depth == 0:
                start_index = index
            depth += 1
        elif char == "}":
            if depth == 0:
                continue
            depth -= 1
            if depth == 0 and start_index is not None:
                candidate = candidate_text[start_index : index + 1]
                loaded = _try_load(candidate)
                if loaded is not None:
                    return loaded

    return None


def escape_control_chars_in_json_string_literals(text: str) -> str:
    """JSONの文字列リテラル内に含まれる制御文字をエスケープする。

    LLM が JSON を出力する際に、`"..."` の中へ改行などの制御文字をそのまま入れてしまうと
    `json.loads` が `Invalid control character` で失敗することがある。

    本関数は best-effort で以下を行う:
        - 文字列リテラル（ダブルクォートで囲まれた範囲）のみを対象に、
          `\\n` / `\\r` / `\\t` などへ置換する。
        - それ以外の制御文字（U+0000..U+001F）は `\\u00XX` へ置換する。

    Args:
        text: JSON文字列（またはJSONの候補文字列）

    Returns:
        制御文字をエスケープした文字列（入力と同一の場合もある）
    """

    if not text:
        return text

    out: list[str] = []
    in_string = False
    escape = False
    for char in text:
        if escape:
            out.append(char)
            escape = False
            continue
        if char == "\\":
            out.append(char)
            if in_string:
                escape = True
            continue
        if char == '"':
            out.append(char)
            in_string = not in_string
            continue

        if in_string:
            if char == "\n":
                out.append("\\n")
                continue
            if char == "\r":
                out.append("\\r")
                continue
            if char == "\t":
                out.append("\\t")
                continue
            if ord(char) < 0x20:
                out.append(f"\\u{ord(char):04x}")
                continue

        out.append(char)

    return "".join(out)
