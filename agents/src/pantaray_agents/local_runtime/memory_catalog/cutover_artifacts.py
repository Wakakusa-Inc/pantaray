from __future__ import annotations

import os
import shutil
from pathlib import Path

from .artifact_paths import confined_artifact_path, memory_revision_relative_path
from .cutover_models import PlannedRecord
from .cutover_support import write_artifact_tree


def materialize_planned_artifacts(
    *, plans: tuple[PlannedRecord, ...], staging_root: Path
) -> tuple[PlannedRecord, ...]:
    materialized: list[PlannedRecord] = []
    for plan in plans:
        if plan.record.body_kind == "inline":
            materialized.append(plan)
            continue
        raw_relative_path = memory_revision_relative_path(
            user_id=plan.record.user_id,
            node_id=plan.node_id,
            revision_id=plan.raw_revision_id,
        )
        raw_path = confined_artifact_path(staging_root, raw_relative_path)
        write_artifact_tree(raw_path, plan.record.documents)
        current_relative_path = raw_relative_path
        if plan.current_revision_id != plan.raw_revision_id:
            current_relative_path = memory_revision_relative_path(
                user_id=plan.record.user_id,
                node_id=plan.node_id,
                revision_id=plan.current_revision_id,
            )
            current_path = confined_artifact_path(staging_root, current_relative_path)
            write_artifact_tree(current_path, plan.current_documents)
        materialized.append(
            PlannedRecord(
                record=plan.record,
                node_id=plan.node_id,
                raw_revision_id=plan.raw_revision_id,
                current_revision_id=plan.current_revision_id,
                current_documents=plan.current_documents,
                raw_artifact_path=raw_relative_path,
                current_artifact_path=current_relative_path,
                links=plan.links,
                quarantine=plan.quarantine,
            )
        )
    return tuple(materialized)


def promote_planned_artifacts(
    *, plans: tuple[PlannedRecord, ...], artifact_root: Path, staging_root: Path
) -> tuple[Path, ...]:
    relative_paths = tuple(
        dict.fromkeys(
            path
            for plan in plans
            for path in (plan.raw_artifact_path, plan.current_artifact_path)
            if path is not None
        )
    )
    promoted: list[Path] = []
    try:
        for relative_path in relative_paths:
            source = confined_artifact_path(staging_root, relative_path)
            destination = confined_artifact_path(artifact_root, relative_path)
            if destination.exists():
                raise FileExistsError(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, destination)
            promoted.append(destination)
            _fsync_directory(destination.parent)
    except (OSError, ValueError):
        for path in reversed(promoted):
            shutil.rmtree(path, ignore_errors=True)
        raise
    return tuple(promoted)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
