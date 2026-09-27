from __future__ import annotations

import pytest

from pantaray_agents.local_runtime.storage.migrations.sql_script import (
    SqlScriptContractError,
    prepare_sql_script,
)


def test_prepare_sql_script_extracts_runner_owned_foreign_key_mode() -> None:
    prepared = prepare_sql_script(
        """
        -- Rebuild requires foreign keys to be disabled outside the transaction.
        PRAGMA foreign_keys = OFF;
        CREATE TABLE example(id INTEGER PRIMARY KEY);
        PRAGMA foreign_keys = ON;
        """
    )

    assert prepared.requires_foreign_keys_disabled is True
    assert prepared.statements == ("CREATE TABLE example(id INTEGER PRIMARY KEY);",)


@pytest.mark.parametrize("directive", ["BEGIN IMMEDIATE", "COMMIT", "ROLLBACK"])
def test_prepare_sql_script_rejects_script_owned_transactions(
    directive: str,
) -> None:
    with pytest.raises(SqlScriptContractError):
        prepare_sql_script(f"/* migration control */\n{directive};")


def test_prepare_sql_script_can_strip_immutable_legacy_transaction_control() -> None:
    prepared = prepare_sql_script(
        "BEGIN IMMEDIATE;\nCREATE TABLE example(id INTEGER);\nCOMMIT;",
        strip_transaction_control=True,
    )

    assert prepared.statements == ("CREATE TABLE example(id INTEGER);",)
