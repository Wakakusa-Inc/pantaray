from __future__ import annotations

from typing import get_args

import pytest

from pantaray_agents.local_runtime.memory_catalog.search_policy import (
    MEMORY_CATALOG_TO_SEARCH_SOURCE,
    MEMORY_SEARCH_FOCUS_SOURCES,
    MEMORY_SEARCH_FOCUS_VALUES,
    MEMORY_SEARCH_TO_CATALOG_SOURCE,
    MemoryCatalogSource,
    MemorySearchFocus,
    MemorySearchSource,
    parse_memory_search_focus,
)


def test_memory_search_source_registry_is_complete() -> None:
    catalog_sources = set(get_args(MemoryCatalogSource))
    search_sources = set(get_args(MemorySearchSource))
    searchable_catalog_sources = catalog_sources

    assert set(MEMORY_CATALOG_TO_SEARCH_SOURCE) == searchable_catalog_sources
    assert set(MEMORY_CATALOG_TO_SEARCH_SOURCE.values()) == search_sources
    assert {
        MEMORY_SEARCH_TO_CATALOG_SOURCE[source] for source in search_sources
    } == searchable_catalog_sources


def test_memory_search_focus_taxonomy_is_complete_and_separated() -> None:
    assert set(MEMORY_SEARCH_FOCUS_VALUES) == set(get_args(MemorySearchFocus))
    assert MEMORY_SEARCH_FOCUS_SOURCES["activity"] == (
        "short_term_insight",
        "activity_summary",
        "activity_description",
        "source_records",
    )
    assert "agent_experience" in MEMORY_SEARCH_FOCUS_SOURCES["all"]
    assert MEMORY_SEARCH_FOCUS_SOURCES["agent_work"] == (
        "actions",
        "action_file_read",
        "agent_experience",
    )
    assert MEMORY_SEARCH_FOCUS_SOURCES["agent_experience"] == ("agent_experience",)


def test_parse_memory_search_focus_rejects_unknown_values() -> None:
    assert parse_memory_search_focus("stable_knowledge") == "stable_knowledge"
    with pytest.raises(ValueError, match="focus is invalid"):
        parse_memory_search_focus("unknown")
