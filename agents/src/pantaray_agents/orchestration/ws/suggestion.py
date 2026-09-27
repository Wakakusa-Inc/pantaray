"""Suggestion フロー（relay・dismiss/resume）の統合 Mixin。"""

from __future__ import annotations

from pantaray_agents.orchestration.ws.suggestion_insight import SuggestionInsightMixin
from pantaray_agents.orchestration.ws.suggestion_relay import SuggestionRelayMixin


class SuggestionFlowMixin(SuggestionRelayMixin, SuggestionInsightMixin):
    """Suggestion の中継とユーザー反応処理の責務をまとめた統合 Mixin。

    Suggestion 自体は runtime（worker job）が起動するため、WS はここで
    起動を行わず、進行中プロセスの中継とユーザー反応の処理だけを担う。
    """
