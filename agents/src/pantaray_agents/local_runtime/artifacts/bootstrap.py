from __future__ import annotations

from pathlib import Path

from ..storage.migrations import MigrationError
from .models import ArtifactStoreLayout
from .paths import (
    ARTIFACT_TEMP_DIRNAME,
    artifact_kind_directory,
    normalize_artifact_root,
)


def bootstrap_local_artifact_store(*, root_path: Path) -> ArtifactStoreLayout:
    normalized_root = normalize_artifact_root(root_path)
    normalized_root.mkdir(parents=True, exist_ok=True)
    if not normalized_root.is_dir():
        raise MigrationError("LOCAL_ARTIFACT_ROOT must resolve to a directory")

    screenshots_dir = normalized_root / artifact_kind_directory("screenshots")
    long_term_insight_dir = normalized_root / artifact_kind_directory(
        "long_term_insight"
    )
    facts_dir = normalized_root / artifact_kind_directory("facts")
    generated_dir = normalized_root / artifact_kind_directory("generated")
    temp_dir = normalized_root / ARTIFACT_TEMP_DIRNAME

    for directory in (
        screenshots_dir,
        long_term_insight_dir,
        facts_dir,
        generated_dir,
        temp_dir,
    ):
        directory.mkdir(parents=True, exist_ok=True)
        if not directory.is_dir():
            raise MigrationError(
                f"artifact bootstrap expected directory: {directory!s}"
            )

    return ArtifactStoreLayout(
        root_path=normalized_root,
        screenshots_dir=screenshots_dir,
        long_term_insight_dir=long_term_insight_dir,
        facts_dir=facts_dir,
        generated_dir=generated_dir,
        temp_dir=temp_dir,
    )
