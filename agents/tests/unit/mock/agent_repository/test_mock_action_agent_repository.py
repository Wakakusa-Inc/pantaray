import pytest

from pantaray_agents.schema.repositories.repository import RepositoryErrorKind

from .shared import (
    UTC,
    MockActionAgentRepository,
    StatusType,
    StepType,
    datetime,
)


class TestMockActionAgentRepository:
    """MockActionAgentRepositoryのテスト"""

    @staticmethod
    def _action_record(
        *,
        action_id: str,
        suggestion_id: str,
        user_id: str,
        final_output: str = "",
        status: str | StatusType = StatusType.PROCESSING,
        created_at: datetime | None = None,
        updated_at: datetime | None = None,
        prompt_name: str = "action/executing",
        prompt_version: str = "test",
    ) -> dict[str, object]:
        created = created_at or datetime.now(UTC)
        updated = updated_at or created
        return {
            "action_id": action_id,
            "suggestion_id": suggestion_id,
            "user_id": user_id,
            "final_output": final_output,
            "status": status,
            "prompt_name": prompt_name,
            "prompt_version": prompt_version,
            "created_at": created,
            "updated_at": updated,
        }

    @staticmethod
    async def _save_action(
        repo: MockActionAgentRepository,
        action_data: dict[str, object],
    ) -> None:
        result = await repo.save_action(
            action_data,
            prompt_name=str(action_data["prompt_name"]),
            prompt_version=str(action_data["prompt_version"]),
        )
        assert result.error is None

    @pytest.mark.asyncio
    async def test_save_and_get_action(self):
        """アクションの保存と取得が正しく機能することをテストします"""
        repo = MockActionAgentRepository()

        # 辞書形式のアクションデータ
        action_data = self._action_record(
            action_id="test-action-1",
            suggestion_id="test-suggestion-1",
            user_id="test-user-1",
            final_output="Test action result",
            status=StatusType.SUCCESS,
        )

        # 保存
        await self._save_action(repo, action_data)

        # 取得
        result = await repo.get_action(
            user_id="test-user-1",
            action_id="test-action-1",
        )

        # 検証
        assert result.error is None
        assert result.data is not None
        assert result.data["action_id"] == "test-action-1"
        assert result.data["suggestion_id"] == "test-suggestion-1"
        assert result.data["final_output"] == "Test action result"

    @pytest.mark.asyncio
    async def test_get_actions_by_user(self):
        """ユーザーIDに基づくアクション取得が正しく機能することをテストします"""
        repo = MockActionAgentRepository()

        # 同じユーザーの複数のアクションを保存
        user_id = "test-user-actions"

        action_data1 = self._action_record(
            action_id="user-action-1",
            suggestion_id="sug-1",
            user_id=user_id,
            final_output="Action result 1",
        )

        action_data2 = self._action_record(
            action_id="user-action-2",
            suggestion_id="sug-2",
            user_id=user_id,
            final_output="Action result 2",
            created_at=datetime(2023, 1, 1),
        )

        # 別ユーザーのアクション
        action_data3 = self._action_record(
            action_id="other-action",
            suggestion_id="sug-3",
            user_id="other-user",
            final_output="Other action",
        )

        await self._save_action(repo, action_data1)
        await self._save_action(repo, action_data2)
        await self._save_action(repo, action_data3)

        # ユーザーのアクションを取得
        result = await repo.get_actions_by_user(user_id, limit=10)

        # 検証
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 2  # 特定ユーザーのアクションのみ
        assert result.data[0]["action_id"] == "user-action-1"  # 新しい方が先に来る
        assert result.data[1]["action_id"] == "user-action-2"

    @pytest.mark.asyncio
    async def test_get_actions_by_suggestion(self):
        """サジェスチョンIDに基づくアクション取得が正しく機能することをテストします"""
        repo = MockActionAgentRepository()

        # 同じサジェスチョンに関連する複数のアクションを保存
        suggestion_id = "test-suggestion-actions"

        action_data1 = self._action_record(
            action_id="sug-action-1",
            suggestion_id=suggestion_id,
            user_id="user-1",
            final_output="Suggestion action 1",
        )

        action_data2 = self._action_record(
            action_id="sug-action-2",
            suggestion_id=suggestion_id,
            user_id="user-1",
            final_output="Suggestion action 2",
            created_at=datetime(2023, 1, 1),
        )

        # 別サジェスチョンのアクション
        action_data3 = self._action_record(
            action_id="other-action",
            suggestion_id="other-suggestion",
            user_id="user-1",
            final_output="Other action",
        )

        await self._save_action(repo, action_data1)
        await self._save_action(repo, action_data2)
        await self._save_action(repo, action_data3)

        # サジェスチョンに関連するアクションを取得
        result = await repo.get_actions_by_suggestion(
            user_id="user-1",
            suggestion_id=suggestion_id,
        )

        # 検証
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 2  # 特定サジェスチョンのアクションのみ
        assert result.data[0]["action_id"] == "sug-action-1"  # 新しい方が先に来る
        assert result.data[1]["action_id"] == "sug-action-2"

    @pytest.mark.asyncio
    async def test_get_actions_by_suggestion_not_found(self):
        """存在しないサジェスチョンIDを指定した場合のエラーハンドリングをテストします"""
        repo = MockActionAgentRepository()

        result = await repo.get_actions_by_suggestion(
            user_id="user-1",
            suggestion_id="non-existent-suggestion",
        )

        assert result.error is not None
        assert "No actions found" in result.error
        assert result.data is None

    @pytest.mark.asyncio
    async def test_save_action_step_requires_user_id(self) -> None:
        """save_action_step は user_id 未指定を fail-closed で拒否する。"""
        repo = MockActionAgentRepository()
        await self._save_action(
            repo,
            self._action_record(
                action_id="test-action-1",
                suggestion_id="test-suggestion-1",
                user_id="test-user-1",
            ),
        )

        result = await repo.save_action_step(
            step_id="step-1",
            action_id="test-action-1",
            step_number=1,
            step_name="supervisor_think",
            step_type=StepType.LLM_OUTPUT,
            llm_prompt_text="prompt",
            llm_response_text="response",
            status="success",
            goal_handle="S",
            short_step_id="S-1-THINK",
            local_step_number=1,
        )

        assert result.error is not None
        assert "user_id is required" in result.error
        assert result.error_kind is RepositoryErrorKind.VALIDATION
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_save_action_step_checks_ownership_and_persists_valid_row(
        self,
    ) -> None:
        """save_action_step は所有検証を行い、有効行のみ保存する。"""
        repo = MockActionAgentRepository()
        await self._save_action(
            repo,
            self._action_record(
                action_id="test-action-2",
                suggestion_id="test-suggestion-2",
                user_id="test-user-2",
            ),
        )

        denied = await repo.save_action_step(
            step_id="step-denied",
            action_id="test-action-2",
            step_number=1,
            step_name="supervisor_think",
            step_type=StepType.LLM_OUTPUT,
            llm_prompt_text="prompt",
            llm_response_text="response",
            status="success",
            goal_handle="S",
            user_id="wrong-user",
            short_step_id="S-1-THINK",
            local_step_number=1,
        )
        assert denied.error is not None
        assert "Action not found" in denied.error
        assert denied.error_kind is RepositoryErrorKind.NOT_FOUND
        assert denied.retryable is False

        success = await repo.save_action_step(
            step_id="step-ok",
            action_id="test-action-2",
            step_number=2,
            step_name="tool::close_requirement",
            step_type=StepType.TOOL_EXECUTION,
            tool_args={
                "tool_id": "close_requirement",
                "args": {
                    "requirement_id": "R1",
                    "status": "done",
                    "reason": "completed",
                },
            },
            tool_output={"status": "success"},
            status="success",
            goal_handle="S",
            user_id="test-user-2",
            short_step_id="S-2-TOOL",
            local_step_number=2,
        )

        assert success.error is None
        assert success.data is not None
        assert success.data["goal_handle"] == "S"
        assert success.data["short_step_id"] == "S-2-TOOL"
        assert success.data["local_step_number"] == 2
        assert success.data.get("created_at")
        assert "user_id" not in success.data

    @pytest.mark.asyncio
    async def test_save_action_step_rejects_invalid_status(self) -> None:
        """save_action_step は DB 制約外の status を fail-closed で拒否する。"""
        repo = MockActionAgentRepository()
        await self._save_action(
            repo,
            self._action_record(
                action_id="test-action-status",
                suggestion_id="test-suggestion-status",
                user_id="test-user-status",
            ),
        )

        result = await repo.save_action_step(
            step_id="step-invalid-status",
            action_id="test-action-status",
            step_number=1,
            step_name="action::warning",
            step_type=StepType.TOOL_EXECUTION,
            tool_args={},
            tool_output={"status": "warning"},
            status="warning",
            goal_handle="S",
            user_id="test-user-status",
            short_step_id="S-1-TOOL",
            local_step_number=1,
        )

        assert result.error is not None
        assert "ActionStepRecord" in result.error
        assert "queued" in result.error
        assert result.error_kind is RepositoryErrorKind.VALIDATION
        assert result.retryable is False

    @pytest.mark.asyncio
    async def test_upsert_action_header_rejects_non_positive_token_budget(self) -> None:
        repo = MockActionAgentRepository()

        result = await repo.upsert_action_header(
            action_id="test-action-budget",
            user_id="test-user-budget",
            suggestion_id="test-suggestion-budget",
            prompt_name="action/executing",
            prompt_version="1.0",
            token_budget=0,
        )

        assert result.data is None
        assert result.error == "token_budget must be a positive integer or null"

    @pytest.mark.asyncio
    async def test_save_action_rejects_non_positive_token_budget(self) -> None:
        repo = MockActionAgentRepository()

        result = await repo.save_action(
            self._action_record(
                action_id="test-action-budget",
                suggestion_id="test-suggestion-budget",
                user_id="test-user-budget",
            ),
            prompt_name="action/executing",
            prompt_version="test",
            token_budget=0,
        )

        assert result.data is None
        assert result.error == "token_budget must be a positive integer or null"

    @pytest.mark.asyncio
    async def test_get_action_rejects_row_missing_status(self) -> None:
        repo = MockActionAgentRepository()
        await repo.save_data(
            "actions",
            {
                "action_id": "invalid-action",
                "suggestion_id": "invalid-suggestion",
                "user_id": "invalid-user",
                "final_output": "",
                "prompt_name": "action/executing",
                "prompt_version": "test",
                "created_at": datetime.now(UTC).isoformat(),
                "updated_at": datetime.now(UTC).isoformat(),
            },
        )

        result = await repo.get_action(
            user_id="invalid-user",
            action_id="invalid-action",
        )

        assert result.data is None
        assert result.error is not None
        assert "status is required" in result.error

    @pytest.mark.asyncio
    async def test_get_action_step_rejects_invalid_step_row_without_raising(
        self,
    ) -> None:
        repo = MockActionAgentRepository()
        await self._save_action(
            repo,
            self._action_record(
                action_id="action-invalid-step",
                suggestion_id="suggestion-invalid-step",
                user_id="user-invalid-step",
            ),
        )
        await repo.save_data(
            "action_steps",
            {
                "step_id": "step-invalid",
                "action_id": "action-invalid-step",
                "step_number": 1,
                "step_name": "supervisor_think",
                "step_type": "llm_output",
                "status": "processing",
                "created_at": datetime.now(UTC).isoformat(),
                # short_step_id/local_step_number/goal_handle を欠落させる
            },
        )

        result = await repo.get_action_step(
            user_id="user-invalid-step",
            step_id="step-invalid",
        )

        assert result.data is None
        assert result.error is not None
