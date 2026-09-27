"""agents テスト共通フィクスチャ"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.unit.agents.action_agent.fixtures import (
    create_local_runtime_db,
    install_local_runtime_env,
)
from tests.unit.local_runtime.action_seed import insert_agent_action

from pantaray_agents.mock.action_agent_repository.mutation_mixin import (
    MockActionAgentMutationMixin,
)


@pytest.fixture(scope="session")
def local_runtime_template_db(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """agents テスト全体で共有する migrated local runtime DB テンプレート。"""

    template_dir = tmp_path_factory.mktemp("agent-local-runtime-template")
    return create_local_runtime_db(db_path=template_dir / "runtime-template.db")


@pytest.fixture(autouse=True)
def configure_agent_unit_tests(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    local_runtime_template_db: Path,
) -> None:
    """agent unit test は常時 local runtime 経路を前提にする。"""

    db_path = tmp_path / "runtime.db"
    shutil.copy2(local_runtime_template_db, db_path)
    install_local_runtime_env(monkeypatch=monkeypatch, db_path=db_path)

    original_upsert = MockActionAgentMutationMixin.upsert_action_header

    async def _upsert_and_seed_local_runtime(self, **kwargs):
        result = await original_upsert(self, **kwargs)
        if result.error is None:
            insert_agent_action(
                db_path=db_path,
                user_id=str(kwargs["user_id"]),
                suggestion_id=str(kwargs["suggestion_id"]),
                action_id=str(kwargs["action_id"]),
            )
        return result

    monkeypatch.setattr(
        MockActionAgentMutationMixin,
        "upsert_action_header",
        _upsert_and_seed_local_runtime,
    )
