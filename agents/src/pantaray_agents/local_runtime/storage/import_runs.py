from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, cast

from .migrations import MigrationError
from .users import ensure_user_row

BUSY_TIMEOUT_PRAGMA_TEMPLATE = "PRAGMA busy_timeout = {timeout_ms};"
FOREIGN_KEYS_ON_PRAGMA = "PRAGMA foreign_keys = ON;"
STATUS_RUNNING: Literal["running"] = "running"
STATUS_COMPLETED: Literal["completed"] = "completed"
STATUS_FAILED: Literal["failed"] = "failed"
ALLOWED_IMPORT_RUN_STATUSES: tuple[str, ...] = (
    STATUS_RUNNING,
    STATUS_COMPLETED,
    STATUS_FAILED,
)
SOURCE_STATUS_RUNNING: Literal["running"] = "running"
SOURCE_STATUS_COMPLETED: Literal["completed"] = "completed"
SOURCE_STATUS_FAILED: Literal["failed"] = "failed"
SOURCE_STATUS_SKIPPED: Literal["skipped"] = "skipped"
ALLOWED_IMPORT_SOURCE_STATUSES: tuple[str, ...] = (
    SOURCE_STATUS_RUNNING,
    SOURCE_STATUS_COMPLETED,
    SOURCE_STATUS_FAILED,
    SOURCE_STATUS_SKIPPED,
)


@dataclass(frozen=True)
class ImportRunRecord:
    import_run_id: str
    user_id: str
    status: Literal["running", "completed", "failed"]
    started_at: str
    completed_at: str | None
    requested_by: str
    force_reindex: bool
    error_code: str | None
    error_message: str | None


@dataclass(frozen=True)
class ImportRunSourceRecord:
    import_run_source_id: str
    import_run_id: str
    source_name: str
    status: Literal["running", "completed", "failed", "skipped"]
    watermark_value: str | None
    imported_count: int
    skipped_count: int
    artifact_repaired_count: int
    started_at: str
    completed_at: str | None
    error_code: str | None
    error_message: str | None


def _configure_connection(connection: sqlite3.Connection, busy_timeout_ms: int) -> None:
    connection.execute(BUSY_TIMEOUT_PRAGMA_TEMPLATE.format(timeout_ms=busy_timeout_ms))
    connection.execute(FOREIGN_KEYS_ON_PRAGMA)


def _validate_busy_timeout(busy_timeout_ms: int) -> None:
    if busy_timeout_ms <= 0:
        raise MigrationError("LOCAL_DB_BUSY_TIMEOUT_MS must be a positive integer")


def _validate_non_empty(value: str, *, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise MigrationError(f"{field_name} must not be empty")
    return normalized


def _validate_import_run_status(
    status: str,
) -> Literal["running", "completed", "failed"]:
    normalized = status.strip().lower()
    if normalized not in ALLOWED_IMPORT_RUN_STATUSES:
        raise MigrationError(
            "import run status must be one of: "
            + ", ".join(ALLOWED_IMPORT_RUN_STATUSES)
        )
    return cast(Literal["running", "completed", "failed"], normalized)


def _validate_import_source_status(
    status: str,
) -> Literal["running", "completed", "failed", "skipped"]:
    normalized = status.strip().lower()
    if normalized not in ALLOWED_IMPORT_SOURCE_STATUSES:
        raise MigrationError(
            "import source status must be one of: "
            + ", ".join(ALLOWED_IMPORT_SOURCE_STATUSES)
        )
    return cast(Literal["running", "completed", "failed", "skipped"], normalized)


def _start_import_run_row(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    user_id: str,
    requested_by: str,
    force_reindex: bool,
) -> str:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_user_id = _validate_non_empty(user_id, field_name="user_id")
    normalized_requested_by = _validate_non_empty(
        requested_by, field_name="requested_by"
    )
    import_run_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            ensure_user_row(connection, user_id=normalized_user_id)
            connection.execute(
                """
                INSERT INTO import_runs(
                    import_run_id,
                    user_id,
                    status,
                    started_at,
                    completed_at,
                    requested_by,
                    force_reindex,
                    error_code,
                    error_message
                ) VALUES (?, ?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'), NULL, ?, ?, NULL, NULL)
                """,
                (
                    import_run_id,
                    normalized_user_id,
                    STATUS_RUNNING,
                    normalized_requested_by,
                    1 if force_reindex else 0,
                ),
            )
    return import_run_id


def _record_import_run_source_row(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
    source_name: str,
    status: str,
    watermark_value: str | None,
    imported_count: int,
    skipped_count: int,
    artifact_repaired_count: int,
    started_at: str,
    completed_at: str | None,
    error_code: str | None,
    error_message: str | None,
) -> str:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_import_run_id = _validate_non_empty(
        import_run_id, field_name="import_run_id"
    )
    normalized_source_name = _validate_non_empty(source_name, field_name="source_name")
    normalized_status = _validate_import_source_status(status)
    if imported_count < 0:
        raise MigrationError("imported_count must be greater than or equal to zero")
    if skipped_count < 0:
        raise MigrationError("skipped_count must be greater than or equal to zero")
    if artifact_repaired_count < 0:
        raise MigrationError(
            "artifact_repaired_count must be greater than or equal to zero"
        )
    import_run_source_id = str(uuid.uuid4())
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            connection.execute(
                """
                INSERT INTO import_run_sources(
                    import_run_source_id,
                    import_run_id,
                    source_name,
                    status,
                    watermark_value,
                    imported_count,
                    skipped_count,
                    artifact_repaired_count,
                    started_at,
                    completed_at,
                    error_code,
                    error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    import_run_source_id,
                    normalized_import_run_id,
                    normalized_source_name,
                    normalized_status,
                    watermark_value,
                    imported_count,
                    skipped_count,
                    artifact_repaired_count,
                    started_at,
                    completed_at,
                    error_code,
                    error_message,
                ),
            )
    return import_run_source_id


def _finalize_import_run_row(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
    status: str,
    error_code: str | None,
    error_message: str | None,
) -> None:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_import_run_id = _validate_non_empty(
        import_run_id, field_name="import_run_id"
    )
    normalized_status = _validate_import_run_status(status)
    if normalized_status == STATUS_RUNNING:
        raise MigrationError("finalize_import_run does not accept running status")
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        with connection:
            cursor = connection.execute(
                """
                UPDATE import_runs
                SET
                    status = ?,
                    completed_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now'),
                    error_code = ?,
                    error_message = ?
                WHERE import_run_id = ?
                """,
                (
                    normalized_status,
                    error_code,
                    error_message,
                    normalized_import_run_id,
                ),
            )
    if cursor.rowcount <= 0:
        raise MigrationError(f"import_run_id not found: {normalized_import_run_id}")


def get_import_run(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
) -> ImportRunRecord | None:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_import_run_id = _validate_non_empty(
        import_run_id, field_name="import_run_id"
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        row = connection.execute(
            """
            SELECT
                import_run_id,
                user_id,
                status,
                started_at,
                completed_at,
                requested_by,
                force_reindex,
                error_code,
                error_message
            FROM import_runs
            WHERE import_run_id = ?
            """,
            (normalized_import_run_id,),
        ).fetchone()
    if row is None:
        return None
    return ImportRunRecord(
        import_run_id=str(row[0]),
        user_id=str(row[1]),
        status=_validate_import_run_status(str(row[2])),
        started_at=str(row[3]),
        completed_at=str(row[4]) if row[4] is not None else None,
        requested_by=str(row[5]),
        force_reindex=bool(row[6]),
        error_code=str(row[7]) if row[7] is not None else None,
        error_message=str(row[8]) if row[8] is not None else None,
    )


def list_import_run_sources(
    *,
    db_path: Path,
    busy_timeout_ms: int,
    import_run_id: str,
) -> tuple[ImportRunSourceRecord, ...]:
    _validate_busy_timeout(busy_timeout_ms)
    normalized_import_run_id = _validate_non_empty(
        import_run_id, field_name="import_run_id"
    )
    with sqlite3.connect(db_path) as connection:
        _configure_connection(connection=connection, busy_timeout_ms=busy_timeout_ms)
        rows = connection.execute(
            """
            SELECT
                import_run_source_id,
                import_run_id,
                source_name,
                status,
                watermark_value,
                imported_count,
                skipped_count,
                artifact_repaired_count,
                started_at,
                completed_at,
                error_code,
                error_message
            FROM import_run_sources
            WHERE import_run_id = ?
            ORDER BY import_run_source_id ASC
            """,
            (normalized_import_run_id,),
        ).fetchall()
    return tuple(
        ImportRunSourceRecord(
            import_run_source_id=str(row[0]),
            import_run_id=str(row[1]),
            source_name=str(row[2]),
            status=_validate_import_source_status(str(row[3])),
            watermark_value=str(row[4]) if row[4] is not None else None,
            imported_count=int(row[5]),
            skipped_count=int(row[6]),
            artifact_repaired_count=int(row[7]),
            started_at=str(row[8]),
            completed_at=str(row[9]) if row[9] is not None else None,
            error_code=str(row[10]) if row[10] is not None else None,
            error_message=str(row[11]) if row[11] is not None else None,
        )
        for row in rows
    )
