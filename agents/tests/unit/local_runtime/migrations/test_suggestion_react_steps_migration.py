from __future__ import annotations

import sqlite3
from pathlib import Path

from .support import apply_migrations, load_default_migrations

MIGRATION_NAME = "0069_suggestion_react_steps.sql"


def test_suggestion_react_steps_migration_creates_auditable_step_table(
    tmp_path: Path,
) -> None:
    migrations = load_default_migrations()
    assert any(migration.name == MIGRATION_NAME for migration in migrations)
    db_path = tmp_path / "runtime.db"
    apply_migrations(
        db_path=db_path,
        busy_timeout_ms=1_000,
        migrations=migrations,
    )

    with sqlite3.connect(db_path) as connection:
        columns = {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(agent_suggestion_run_steps)"
            )
        }
    assert "thinking" not in columns
    assert {
        "suggestion_id",
        "step_number",
        "step_kind",
        "status",
        "llm_prompt_text",
        "llm_response_text",
        "tool_name",
        "tool_input_json",
        "tool_output_json",
        "error_code",
        "error_message",
    } <= columns
