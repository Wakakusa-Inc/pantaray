from __future__ import annotations

import sqlite3

from pantaray_agents.local_runtime.storage.migrations import (
    MigrationSpec,
    _configure_connection,
    apply_migrations,
)
from pantaray_agents.local_runtime.storage.migrations import (
    load_default_migrations as _load_default_migrations,
)

_PRE_RESET_SCHEMA_VERSION = 88

__all__ = [
    "ACTION_TERMINAL_RUNTIME_REPAIRS_MIGRATION_NAME",
    "DROP_FEATURE_READINESS_MIGRATION_NAME",
    "FACT_BRIEF_BACKFILL_MIGRATION_NAME",
    "LATEST_LOCAL_RUNTIME_SCHEMA_VERSION",
    "LATEST_LOCAL_RUNTIME_MIGRATION_NAME",
    "MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME",
    "MEMORY_SEARCH_ROW_FTS_MIGRATION_NAME",
    "SUGGESTION_REACTION_TEXT_DOMAIN_MIGRATION_NAME",
    "VIRTUAL_WORKSPACE_MANIFEST_MIGRATION_NAME",
    "POST_ACTION_PIPELINE_PROCESS_KIND_MIGRATION_NAME",
    "REMOVE_INTERVENTION_MODE_MIGRATION_NAME",
    "_configure_connection",
    "_insert_user",
    "_migrations_before",
    "_migrations_through",
    "apply_migrations",
    "load_default_migrations",
]


def load_default_migrations() -> tuple[MigrationSpec, ...]:
    return tuple(
        migration
        for migration in _load_default_migrations()
        if migration.version <= _PRE_RESET_SCHEMA_VERSION
    )


_DEFAULT_MIGRATIONS = load_default_migrations()
LATEST_LOCAL_RUNTIME_SCHEMA_VERSION = _DEFAULT_MIGRATIONS[-1].version
LATEST_LOCAL_RUNTIME_MIGRATION_NAME = _DEFAULT_MIGRATIONS[-1].name
REMOVE_INTERVENTION_MODE_MIGRATION_NAME = "0028_remove_intervention_mode.sql"
POST_ACTION_PIPELINE_PROCESS_KIND_MIGRATION_NAME = (
    "0031_post_action_pipeline_process_kind.sql"
)
ACTION_TERMINAL_RUNTIME_REPAIRS_MIGRATION_NAME = (
    "0032_action_terminal_runtime_repairs.sql"
)
DROP_FEATURE_READINESS_MIGRATION_NAME = "0033_drop_feature_readiness.sql"
MEMORY_SEARCH_ROW_FTS_MIGRATION_NAME = "0034_memory_search_row_fts.sql"
SUGGESTION_REACTION_TEXT_DOMAIN_MIGRATION_NAME = (
    "0035_suggestion_reaction_text_domain.sql"
)
VIRTUAL_WORKSPACE_MANIFEST_MIGRATION_NAME = "0036_virtual_workspace_manifest.sql"
MANIFEST_RUNTIME_AUTHORITY_MIGRATION_NAME = "0037_manifest_runtime_authority.sql"
FACT_BRIEF_BACKFILL_MIGRATION_NAME = "0052_backfill_fact_brief_runs.sql"


def _migration_index_by_name(
    migrations: tuple[MigrationSpec, ...],
    migration_name: str,
) -> int:
    for index, migration in enumerate(migrations):
        if migration.name == migration_name:
            return index
    raise AssertionError(f"Migration not found: {migration_name}")


def _migrations_before(
    migrations: tuple[MigrationSpec, ...],
    migration_name: str,
) -> tuple[MigrationSpec, ...]:
    return migrations[: _migration_index_by_name(migrations, migration_name)]


def _migrations_through(
    migrations: tuple[MigrationSpec, ...],
    migration_name: str,
) -> tuple[MigrationSpec, ...]:
    return migrations[: _migration_index_by_name(migrations, migration_name) + 1]


def _insert_user(connection: sqlite3.Connection, user_id: str) -> None:
    connection.execute(
        """
        INSERT INTO users(
            user_id,
            ui_language,
            created_at,
            updated_at
        ) VALUES (?, 'ja', '2026-03-23T00:00:00Z', '2026-03-23T00:00:00Z')
        """,
        (user_id,),
    )
