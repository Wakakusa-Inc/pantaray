"""タグ認識ストリーミングの共通ユーティリティ。

<final_answer> など、開始・終了タグで囲まれた内容のみを逐次配信するための
抽出器と補助関数を提供する。Action の中間イベント等にも拡張可能。
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Final


def chunk_text(text: str, *, max_chars: int = 240) -> list[str]:
    """与えられた文字列を概ね max_chars 以下のサイズに分割する。

    できる限り文区切り（。！？）や空白で分割し、自然な境界を優先する。
    フォールバックとして固定長で分割する。
    """
    text = text.strip()
    if not text:
        return []
    if len(text) <= max_chars:
        return [text]

    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(len(text), start + max_chars)
        window = text[start:end]
        split_pos = max(
            window.rfind("。"),
            window.rfind("！"),
            window.rfind("？"),
            window.rfind("\n"),
            window.rfind(" "),
        )
        if split_pos <= 0:
            split_pos = len(window)
        chunk = window[:split_pos].strip()
        if not chunk:
            chunk = window.strip()
            split_pos = len(window)
        chunks.append(chunk)
        start += split_pos
    return [c for c in chunks if c]


class TagStreamingExtractor:
    """開始・終了タグに挟まれた内側テキストのみを順次抽出する。

    - フィードされたテキストは内部バッファに蓄積される
    - 開始タグ検出前は何も返さない
    - 開始タグ検出後、終了タグが出るまでの新規分を返す
    - 終了タグ検出後はそれ以降は返さない
    """

    def __init__(self, open_tag: str, close_tag: str) -> None:
        self.open_tag: Final[str] = open_tag
        self.close_tag: Final[str] = close_tag
        self._buffer: str = ""
        self._started: bool = False
        self._ended: bool = False
        self._emit_pos: int = 0  # 直近までに送出済みのバッファ位置

    @property
    def ended(self) -> bool:
        return self._ended

    def feed(self, text: str) -> list[str]:
        """新たなチャンクを与えて、配信対象の新規セグメントを返す。"""
        if not text or self._ended:
            return []
        self._buffer += text

        emitted: list[str] = []

        if not self._started:
            start_idx = self._buffer.find(self.open_tag)
            if start_idx != -1:
                self._started = True
                self._emit_pos = start_idx + len(self.open_tag)
            else:
                return []

        end_idx = self._buffer.find(self.close_tag, self._emit_pos)
        if end_idx != -1:
            segment = self._buffer[self._emit_pos : end_idx]
            if segment:
                emitted.append(segment)
            self._ended = True
        else:
            segment = self._buffer[self._emit_pos :]
            if segment:
                emitted.append(segment)
                self._emit_pos = len(self._buffer)

        return emitted


class MultiTagStreamingExtractor:
    """複数タグの逐次抽出器（非ネスト前提）。

    例: [ ("<answer>", "</answer>", "answer_chunk"), ("<citation>", "</citation>", "citation_chunk") ]

    制限:
    - タグは非ネスト・直列出力を想定（LLMが同時並行で複数タグを interleave しない前提）
    - feedで与えられたテキストに対して、開始タグ→終了タグの順で検出し、その区間の内側のみを
      (event, segment) として順次返す。終了タグが見つからない場合は次のfeedで継続抽出。
    """

    def __init__(self, specs: Iterable[tuple[str, str, str]]) -> None:
        self.specs: list[tuple[str, str, str]] = list(specs)
        self._buffer: str = ""
        self._active_idx: int | None = None
        self._emit_pos: int = 0

    def feed(self, text: str) -> list[tuple[str, str]]:
        """テキストを与え、(event, segment) のリストを返す。

        Returns:
            list[tuple[str, str]]: [(event_name, segment_text), ...]
        """
        if not text:
            return []
        self._buffer += text
        emitted: list[tuple[str, str]] = []

        def find_next_open(start_from: int) -> tuple[int, int] | None:
            """バッファ中の最も早い開始タグと、そのspecインデックスを返す。"""
            best_idx: int | None = None
            best_spec: int | None = None
            for i, (open_tag, _close, _ev) in enumerate(self.specs):
                idx = self._buffer.find(open_tag, start_from)
                if idx != -1 and (best_idx is None or idx < best_idx):
                    best_idx = idx
                    best_spec = i
            return (
                (best_idx, best_spec)
                if best_idx is not None and best_spec is not None
                else None
            )

        # アクティブなタグがない場合は次の開始タグを探す
        if self._active_idx is None:
            found = find_next_open(0)
            if found is None:
                return []
            start_idx, spec_idx = found
            open_tag, _close_tag, _ev = self.specs[spec_idx]
            self._active_idx = spec_idx
            self._emit_pos = start_idx + len(open_tag)

        # アクティブなタグの終了を探す。見つからなければ未配信部分を返し、位置更新。
        while self._active_idx is not None:
            open_tag, close_tag, event_name = self.specs[self._active_idx]
            end_idx = self._buffer.find(close_tag, self._emit_pos)
            if end_idx != -1:
                segment = self._buffer[self._emit_pos : end_idx]
                if segment:
                    emitted.append((event_name, segment))
                # 次の開始タグをこの位置以降で探す
                next_from = end_idx + len(close_tag)
                self._active_idx = None
                found = find_next_open(next_from)
                if found is None:
                    # 以降のfeedを待つ
                    break
                start_idx, spec_idx = found
                self._active_idx = spec_idx
                self._emit_pos = start_idx + len(self.specs[spec_idx][0])
            else:
                # 閉じタグ未検出: 現在までの未配信分を返し、emit位置を末尾に
                segment = self._buffer[self._emit_pos :]
                if segment:
                    emitted.append((event_name, segment))
                    self._emit_pos = len(self._buffer)
                break

        return emitted
