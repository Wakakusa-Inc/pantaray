from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ArtifactKind = Literal["screenshots", "long_term_insight", "facts", "generated"]


@dataclass(frozen=True, slots=True)
class ArtifactStoreLayout:
    root_path: Path
    screenshots_dir: Path
    long_term_insight_dir: Path
    facts_dir: Path
    generated_dir: Path
    temp_dir: Path


@dataclass(frozen=True, slots=True)
class ManagedArtifactLocation:
    kind: ArtifactKind
    relative_path: str
    absolute_path: Path


@dataclass(frozen=True, slots=True)
class ManagedArtifactWriteResult:
    kind: ArtifactKind
    relative_path: str
    absolute_path: Path
    checksum_sha256: str
    file_size_bytes: int
