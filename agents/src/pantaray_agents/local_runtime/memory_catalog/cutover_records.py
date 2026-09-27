from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from .errors import MemoryCutoverError
from .models import MemoryBodyKind, MemoryDocument, MemorySource


@dataclass(frozen=True, slots=True)
class LegacyMemoryRecord:
    user_id: str
    source: MemorySource
    source_record_id: str
    body_kind: MemoryBodyKind
    documents: tuple[MemoryDocument, ...]
    created_at: str
    artifact_root_path: str | None
    memory_keys: tuple[str, ...]
    evidence_source_ids: tuple[str, ...] = ()


_INLINE_SOURCES: tuple[tuple[str, str, str, MemorySource], ...] = (
    ("activity_logs", "log_id", "description", "activity_log"),
    ("activity_summaries", "summary_id", "summary", "activity_summary"),
    ("agent_suggestions", "suggestion_id", "answer", "suggestion"),
    ("agent_actions", "action_id", "final_output", "action"),
    (
        "agent_insights",
        "insight_id",
        "short_term_insight_data",
        "short_term_insight",
    ),
)


def load_legacy_memory_records(
    *, connection: sqlite3.Connection, artifact_root: Path
) -> tuple[LegacyMemoryRecord, ...]:
    records: list[LegacyMemoryRecord] = []
    for table, id_column, body_column, source in _INLINE_SOURCES:
        records.extend(
            _load_inline_records(
                connection=connection,
                table=table,
                id_column=id_column,
                body_column=body_column,
                source=source,
            )
        )
    records.extend(
        _load_fact_artifacts(connection=connection, artifact_root=artifact_root)
    )
    records.extend(
        _load_long_term_artifacts(connection=connection, artifact_root=artifact_root)
    )
    identities = [
        (record.user_id, record.source, record.source_record_id) for record in records
    ]
    if len(identities) != len(set(identities)):
        raise MemoryCutoverError(
            "legacy inventory contains duplicate memory identities"
        )
    return tuple(records)


def _load_inline_records(
    *,
    connection: sqlite3.Connection,
    table: str,
    id_column: str,
    body_column: str,
    source: MemorySource,
) -> tuple[LegacyMemoryRecord, ...]:
    source_ids = "source_ids" if table == "activity_summaries" else "NULL"
    rows = connection.execute(
        f"""
        SELECT user_id, {id_column} AS record_id, {body_column} AS body,
               created_at, {source_ids} AS evidence_source_ids
        FROM {table}
        WHERE status = 'success' AND {body_column} IS NOT NULL
          AND TRIM({body_column}) != ''
        ORDER BY user_id, created_at, {id_column}
        """
    ).fetchall()
    out: list[LegacyMemoryRecord] = []
    for row in rows:
        record_id = str(row["record_id"])
        evidence = _json_string_list(row["evidence_source_ids"])
        out.append(
            LegacyMemoryRecord(
                user_id=str(row["user_id"]),
                source=source,
                source_record_id=record_id,
                body_kind="inline",
                documents=(MemoryDocument("body.md", str(row["body"])),),
                created_at=str(row["created_at"]),
                artifact_root_path=None,
                memory_keys=(f"{source}:{record_id}",),
                evidence_source_ids=evidence,
            )
        )
    return tuple(out)


def _load_fact_artifacts(
    *, connection: sqlite3.Connection, artifact_root: Path
) -> tuple[LegacyMemoryRecord, ...]:
    rows = connection.execute(
        """
        SELECT artifacts.user_id, artifacts.source_record_id, artifacts.root_path,
               artifacts.logical_created_at
        FROM memory_artifacts AS artifacts
        JOIN agent_facts AS facts
          ON facts.user_id = artifacts.user_id
         AND facts.fact_id = artifacts.source_record_id
        WHERE artifacts.source_type = 'facts' AND facts.status = 'success'
        ORDER BY artifacts.user_id, artifacts.logical_updated_at, artifacts.source_record_id
        """
    ).fetchall()
    return tuple(
        _artifact_record(
            connection=connection,
            artifact_root=artifact_root,
            user_id=str(row["user_id"]),
            source="fact",
            source_record_id=str(row["source_record_id"]),
            root_path=str(row["root_path"]),
            created_at=str(row["logical_created_at"]),
            memory_keys=(f"fact:{row['source_record_id']}",),
        )
        for row in rows
    )


def _load_long_term_artifacts(
    *, connection: sqlite3.Connection, artifact_root: Path
) -> tuple[LegacyMemoryRecord, ...]:
    rows = connection.execute(
        """
        SELECT artifacts.user_id, artifacts.source_record_id, artifacts.root_path,
               artifacts.logical_created_at, artifacts.logical_updated_at
        FROM memory_artifacts AS artifacts
        WHERE artifacts.source_type = 'long_term_insight'
        ORDER BY artifacts.user_id, artifacts.logical_updated_at DESC
        """
    ).fetchall()
    latest_by_user: dict[str, sqlite3.Row] = {}
    aliases_by_user: dict[str, list[str]] = {}
    for row in rows:
        user_id = str(row["user_id"])
        latest_by_user.setdefault(user_id, row)
        aliases_by_user.setdefault(user_id, []).append(
            f"long_term_insight:{row['source_record_id']}"
        )
    return tuple(
        _artifact_record(
            connection=connection,
            artifact_root=artifact_root,
            user_id=user_id,
            source="long_term_insight",
            source_record_id=user_id,
            root_path=str(row["root_path"]),
            created_at=str(row["logical_created_at"]),
            memory_keys=tuple(dict.fromkeys(aliases_by_user[user_id])),
        )
        for user_id, row in latest_by_user.items()
    )


def _artifact_record(
    *,
    connection: sqlite3.Connection,
    artifact_root: Path,
    user_id: str,
    source: MemorySource,
    source_record_id: str,
    root_path: str,
    created_at: str,
    memory_keys: tuple[str, ...],
) -> LegacyMemoryRecord:
    rows = connection.execute(
        """
        SELECT files.relative_path, files.sha256
        FROM memory_artifact_files AS files
        JOIN memory_artifacts AS artifacts ON artifacts.artifact_id = files.artifact_id
        WHERE artifacts.user_id = ? AND artifacts.source_type = ?
          AND artifacts.source_record_id = ?
        ORDER BY files.relative_path
        """,
        (
            user_id,
            "facts" if source == "fact" else "long_term_insight",
            source_record_id if source == "fact" else memory_keys[0].partition(":")[2],
        ),
    ).fetchall()
    documents: list[MemoryDocument] = []
    for row in rows:
        relative_path = str(row["relative_path"])
        path = _confined_path(artifact_root, root_path, relative_path)
        if not path.is_file():
            raise MemoryCutoverError(f"legacy artifact file is missing: {path}")
        content = path.read_text(encoding="utf-8")
        expected_sha256 = str(row["sha256"] or "").strip()
        actual_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
        if expected_sha256 and expected_sha256 != actual_sha256:
            raise MemoryCutoverError(f"legacy artifact hash mismatch: {path}")
        documents.append(MemoryDocument(relative_path, content))
    if not documents:
        raise MemoryCutoverError(
            f"legacy artifact has no readable files: {source}:{source_record_id}"
        )
    return LegacyMemoryRecord(
        user_id=user_id,
        source=source,
        source_record_id=source_record_id,
        body_kind="artifact_tree",
        documents=tuple(documents),
        created_at=created_at,
        artifact_root_path=root_path,
        memory_keys=memory_keys,
    )


def _confined_path(root: Path, root_path: str, relative_path: str) -> Path:
    resolved_root = root.resolve()
    candidate = (root / root_path / relative_path).resolve()
    if resolved_root not in candidate.parents:
        raise MemoryCutoverError("legacy artifact path escapes the runtime root")
    return candidate


def _json_string_list(value: object) -> tuple[str, ...]:
    if not isinstance(value, str) or not value:
        return ()
    import json

    parsed = json.loads(value)
    if not isinstance(parsed, list) or any(
        not isinstance(item, str) for item in parsed
    ):
        raise MemoryCutoverError("activity summary source_ids must be a string array")
    return tuple(parsed)
