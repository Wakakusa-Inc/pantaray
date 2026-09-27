import pytest

from .shared import MockInsightAgentRepository, StatusType, datetime


class TestMockInsightAgentRepository:
    """MockInsightAgentRepositoryのテスト"""

    @pytest.mark.asyncio
    async def test_save_and_get_insight(self):
        """インサイトの保存と取得が正しく機能することをテストします"""
        repo = MockInsightAgentRepository()

        # インサイトデータを保存
        now = datetime.now()
        insight_id = "test-insight-1"

        await repo.save_insight(
            insight_id=insight_id,
            current_insight_data="Current insight data",
            insight_data="Long-term insight data",
            thinking="Insight thinking process",
            facts="Observed facts",
            created_at=now,
            user_id="test-user-insight",
            suggestion_id="test-suggestion-insight",
        )

        # 取得
        result = await repo.get_insight(insight_id)

        # 検証
        assert result.error is None
        assert result.data is not None
        assert result.data["insight_id"] == insight_id
        assert result.data["current_insight_data"] == "Current insight data"
        assert result.data["insight_data"] == "Long-term insight data"
        assert result.data["thinking"] == "Insight thinking process"
        assert result.data["facts"] == "Observed facts"
        assert result.data["user_id"] == "test-user-insight"

    @pytest.mark.asyncio
    async def test_get_missing_insight_returns_empty_result(self):
        repo = MockInsightAgentRepository()

        result = await repo.get_insight("missing-insight")

        assert result.error is None
        assert result.data is None

    @pytest.mark.asyncio
    async def test_empty_string_handling(self):
        """空文字列が適切に処理されることをテストします"""
        repo = MockInsightAgentRepository()

        # 空文字列のデータを保存
        insight_id = "test-insight-empty"

        await repo.save_insight(
            insight_id=insight_id,
            current_insight_data="",  # 空文字列
            insight_data="",  # 空文字列
            thinking="Thinking",
            facts="Facts",
            created_at=datetime.now(),
            user_id="test-user",
        )

        # 取得
        result = await repo.get_insight(insight_id)

        # 検証 - 空文字列ではなく空白に変換されているはず
        assert result.error is None
        assert result.data is not None
        assert result.data["current_insight_data"] == " "  # 空白に変換
        assert result.data["insight_data"] == " "  # 空白に変換

    @pytest.mark.asyncio
    async def test_update_insight(self):
        """インサイトの更新が正しく機能することをテストします"""
        repo = MockInsightAgentRepository()

        # インサイトデータを保存
        insight_id = "test-insight-update"

        # 初期データ
        await repo.save_insight(
            insight_id=insight_id,
            current_insight_data="Initial current data",
            insight_data="Initial insight data",
            thinking="Initial thinking",
            facts="Initial facts",
            created_at=datetime.now(),
            user_id="test-user",
        )

        # 更新
        update_result = await repo.update_insight(
            insight_id=insight_id,
            insight_data="Updated insight data",
            status=StatusType.SUCCESS,
        )

        # 更新結果の検証
        assert update_result.error is None
        assert update_result.data is not None
        assert update_result.data["insight_data"] == "Updated insight data"
        assert "updated_at" in update_result.data

        # 更新後のデータを取得して確認
        get_result = await repo.get_insight(insight_id)
        assert get_result.data["insight_data"] == "Updated insight data"
        assert (
            get_result.data["current_insight_data"] == "Initial current data"
        )  # 変更されていない
        assert get_result.data["facts"] == "Initial facts"  # 変更されていない

    @pytest.mark.asyncio
    async def test_update_insight_not_found(self):
        """存在しないインサイトの更新時のエラーハンドリングをテストします"""
        repo = MockInsightAgentRepository()

        result = await repo.update_insight(
            insight_id="non-existent-insight",
            insight_data="Updated data",
        )

        assert result.error is not None
        assert "not found" in result.error
        assert result.data is None

    @pytest.mark.asyncio
    async def test_get_insights(self):
        """ユーザーのインサイト一覧取得が正しく機能することをテストします"""
        repo = MockInsightAgentRepository()

        # 同じユーザーの複数のインサイトを保存
        user_id = "test-user-multiple-insights"

        # 1つ目のインサイト（古い）
        await repo.save_insight(
            insight_id="multi-insight-1",
            current_insight_data="Current 1",
            insight_data="Insight 1",
            thinking="Thinking 1",
            facts="Facts 1",
            created_at=datetime(2023, 1, 1),
            user_id=user_id,
        )

        # 2つ目のインサイト（新しい）
        await repo.save_insight(
            insight_id="multi-insight-2",
            current_insight_data="Current 2",
            insight_data="Insight 2",
            thinking="Thinking 2",
            facts="Facts 2",
            created_at=datetime.now(),
            user_id=user_id,
        )

        # 別ユーザーのインサイト
        await repo.save_insight(
            insight_id="other-insight",
            current_insight_data="Other current",
            insight_data="Other insight",
            thinking="Other thinking",
            facts="Other facts",
            created_at=datetime.now(),
            user_id="other-user",
        )

        # インサイト一覧を取得
        result = await repo.get_insights(user_id, limit=10)

        # 検証
        assert result.error is None
        assert result.data is not None
        assert len(result.data) == 2  # 特定ユーザーのインサイトのみ
        assert result.data[0]["insight_id"] == "multi-insight-2"  # 新しい方が先に来る
        assert result.data[1]["insight_id"] == "multi-insight-1"
