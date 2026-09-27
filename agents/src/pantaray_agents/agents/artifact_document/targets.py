from __future__ import annotations

from pantaray_agents.config_tunables import load_local_runtime_tunables

from .store import ArtifactDocumentStore
from .target import ArtifactDocumentTarget

_ARTIFACT_PATHS = load_local_runtime_tunables().artifact_paths

LONG_TERM_INSIGHT_TARGET = ArtifactDocumentTarget(
    logical_path="long_term.md",
    kind="long_term_insight",
    template=_ARTIFACT_PATHS.long_term_insight_storage_path_template,
    read_error_message="failed to fetch long-term insight from storage",
    conflict_error_message=(
        "long-term insight conflict detected "
        "(storage content changed since patch base was read)"
    ),
    empty_user_error_message="user_id が空です",
)

STRUCTURED_FACTS_TARGET = ArtifactDocumentTarget(
    logical_path="structured_facts.md",
    kind="facts",
    template=_ARTIFACT_PATHS.structured_facts_storage_path_template,
    read_error_message="failed to fetch structured facts from storage",
    conflict_error_message=(
        "structured facts conflict detected "
        "(storage content changed since patch base was read)"
    ),
)

LONG_TERM_INSIGHT_STORE = ArtifactDocumentStore(LONG_TERM_INSIGHT_TARGET)
STRUCTURED_FACTS_STORE = ArtifactDocumentStore(STRUCTURED_FACTS_TARGET)
