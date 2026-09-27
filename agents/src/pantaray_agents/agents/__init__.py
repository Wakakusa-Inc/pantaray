"""エージェント種別ごとの公開アクセスポイント。"""

from importlib import import_module

_MODULE_BY_EXPORT = {
    "ActionAgent": ".action_agent",
    "ActivitySummaryAgent": ".activity_summary_agent",
    "InsightAgent": ".insight_agent",
    "SuggestionAgent": ".suggestion_agent",
}

__all__ = [
    "ActionAgent",
    "ActivitySummaryAgent",
    "InsightAgent",
    "SuggestionAgent",
]


def __getattr__(name: str) -> object:
    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value
