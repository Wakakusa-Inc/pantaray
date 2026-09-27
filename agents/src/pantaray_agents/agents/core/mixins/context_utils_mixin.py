"""コンテキスト/前処理ユーティリティのミックスイン。

本モジュールでは Any 型を使用せず、JSON互換の明示型と
日時型(`datetime | str | None`)のみを用いて型安全性を担保する。
"""

from __future__ import annotations

from typing import TypedDict

from ....schema.agent.base import JSONValue

type ContextMetadata = dict[str, JSONValue]


class _InsightItem(TypedDict):
    """`insights` 要素の最小形。"""

    insight_data: JSONValue


class _SearchResultItem(TypedDict):
    """`search_results` 要素の最小形。"""

    search_data: JSONValue


class _SuggestionItem(TypedDict, total=False):
    """`suggestions` 要素の最小形。`thinking`/`result` は文字列想定。"""

    thinking: str
    result: str


class ContextUtilsMixin:
    """画像抽出/文字列分割/プロンプト用整形などの共通処理を提供する。"""

    # デフォルトのGeminiペイロード上限（テキスト+画像の合算）: 20MB
    # BaseAgent 等で `MAX_GEMINI_PAYLOAD_BYTES` が存在しない場合の安全なフォールバック。
    DEFAULT_MAX_GEMINI_PAYLOAD_BYTES = 20 * 1024 * 1024

    def _get_max_payload_bytes(self) -> int:
        """画像とテキストの合計バイト上限を取得する。

        - 呼び出し側クラスが `MAX_GEMINI_PAYLOAD_BYTES` を持つ場合はそれを使用
        - 未定義/不正値の場合は `DEFAULT_MAX_GEMINI_PAYLOAD_BYTES` を返す
        """
        value = getattr(self, "MAX_GEMINI_PAYLOAD_BYTES", None)
        if isinstance(value, int) and not isinstance(value, bool) and value > 0:
            return value
        return self.DEFAULT_MAX_GEMINI_PAYLOAD_BYTES

    def _format_context_data(
        self, context: dict[str, JSONValue]
    ) -> dict[str, JSONValue]:
        """コンテキスト辞書からプロンプト整形に必要な要素のみを抽出・正規化する。

        Args:
            context: JSON互換の辞書

        Returns:
            dict[str, JSONValue]: 整形済みのコンテキスト
        """

        insights_list = self._insight_items(context.get("insights"))
        search_results_list = self._search_result_items(context.get("search_results"))
        suggestions_list = self._suggestion_items(context.get("suggestions"))
        metadata = self._context_metadata(context.get("metadata"))

        suggestions: list[JSONValue] = []
        for suggestion in suggestions_list:
            thinking_raw = suggestion.get("thinking")
            thinking = (
                thinking_raw
                if isinstance(thinking_raw, str) and thinking_raw.strip()
                else None
            )
            suggestions.append(
                {"thinking": thinking, "result": suggestion.get("result", "")}
            )

        return {
            "metadata": metadata,
            "insights": [
                i["insight_data"] for i in insights_list if "insight_data" in i
            ],
            "search_results": [
                r["search_data"] for r in search_results_list if "search_data" in r
            ],
            "suggestions": suggestions,
        }

    @staticmethod
    def _insight_items(value: JSONValue | None) -> list[_InsightItem]:
        if not isinstance(value, list):
            return []
        items: list[_InsightItem] = []
        for item in value:
            if isinstance(item, dict) and "insight_data" in item:
                items.append({"insight_data": item["insight_data"]})
        return items

    @staticmethod
    def _search_result_items(value: JSONValue | None) -> list[_SearchResultItem]:
        if not isinstance(value, list):
            return []
        items: list[_SearchResultItem] = []
        for item in value:
            if isinstance(item, dict) and "search_data" in item:
                items.append({"search_data": item["search_data"]})
        return items

    @staticmethod
    def _suggestion_items(value: JSONValue | None) -> list[_SuggestionItem]:
        if not isinstance(value, list):
            return []
        items: list[_SuggestionItem] = []
        for item in value:
            if not isinstance(item, dict):
                continue
            suggestion: _SuggestionItem = {}
            thinking = item.get("thinking")
            result = item.get("result")
            if isinstance(thinking, str):
                suggestion["thinking"] = thinking
            if isinstance(result, str):
                suggestion["result"] = result
            items.append(suggestion)
        return items

    @staticmethod
    def _context_metadata(value: JSONValue | None) -> ContextMetadata:
        return value if isinstance(value, dict) else {}

    def _iter_string_chunks(self, text: str, *, max_chars: int = 240) -> list[str]:
        """文字列を最大長で分割し、文末優先でチャンク化する。"""
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
