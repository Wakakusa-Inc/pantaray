import pytest

from pantaray_agents.mock.mock_repository import MockRepository
from pantaray_agents.schema.repositories.repository import RepositoryResult


@pytest.fixture
def mock_repository():
    """テスト用のMockRepositoryインスタンスを作成するフィクスチャ"""
    # 各テストの前にデータをクリアする
    MockRepository.clear_data()
    return MockRepository()


@pytest.mark.asyncio
async def test_save_and_get_suggestion(mock_repository: MockRepository):
    """suggestionの保存と取得をテストする"""
    suggestion_id = "sug-test-123"
    data = {"answer": "Test suggestion", "thinking": "Test thinking"}
    await mock_repository.save_suggestion(suggestion_id, data, "test-user")

    result = await mock_repository.get_suggestion(suggestion_id)
    assert isinstance(result, RepositoryResult)
    assert result.data is not None
    assert result.data["suggestion_id"] == suggestion_id
    assert result.data["answer"] == "Test suggestion"
    assert result.data["thinking"] == "Test thinking"
    assert result.data["user_id"] == "test-user"
    assert "created_at" in result.data


@pytest.mark.asyncio
async def test_get_suggestion_not_found(mock_repository: MockRepository):
    """存在しないsuggestionの取得をテストする"""
    result = await mock_repository.get_suggestion("sug-non-existent")
    assert isinstance(result, RepositoryResult)
    assert result.data is None
    assert result.error is not None
    assert result.error == "Suggestion sug-non-existent not found"


@pytest.mark.asyncio
async def test_save_and_get_action(mock_repository: MockRepository):
    """actionの保存と取得をテストする"""
    action_id = "act-test-456"
    suggestion_id = "sug-for-act"
    data = {"answer": "Test action", "thinking": "Action thinking"}
    await mock_repository.save_action(
        action_id, suggestion_id, data, "test-user-action"
    )

    result = await mock_repository.get_action(action_id)
    assert isinstance(result, RepositoryResult)
    assert result.data is not None
    assert result.data["action_id"] == action_id
    assert result.data["suggestion_id"] == suggestion_id
    assert result.data["answer"] == "Test action"
    assert result.data["thinking"] == "Action thinking"
    assert result.data["user_id"] == "test-user-action"
    assert "created_at" in result.data


@pytest.mark.asyncio
async def test_get_action_not_found(mock_repository: MockRepository):
    """存在しないactionの取得をテストする"""
    result = await mock_repository.get_action("act-non-existent")
    assert isinstance(result, RepositoryResult)
    assert result.data is None
    assert result.error is not None
    assert result.error == "Action act-non-existent not found"


@pytest.mark.asyncio
async def test_save_and_get_insight(mock_repository: MockRepository):
    """insightの保存と取得をテストする"""
    insight_id = "ins-test-789"
    data = {
        "insight_data": "Initial insight data",
        "current_insight_data": "Current insight data",
        "facts": "Some facts",
        "thinking": "Insight thinking",
    }
    await mock_repository.save_insight(insight_id, data, "test-user-insight")

    result = await mock_repository.get_insight(insight_id)
    assert isinstance(result, RepositoryResult)
    assert result.data is not None
    assert result.data["insight_id"] == insight_id
    assert result.data["insight_data"] == "Initial insight data"
    assert result.data["current_insight_data"] == "Current insight data"
    assert result.data["facts"] == "Some facts"
    assert result.data["thinking"] == "Insight thinking"
    assert result.data["user_id"] == "test-user-insight"
    assert "created_at" in result.data


@pytest.mark.asyncio
async def test_get_insight_not_found(mock_repository: MockRepository):
    """存在しないinsightの取得をテストする"""
    result = await mock_repository.get_insight("ins-non-existent")
    assert isinstance(result, RepositoryResult)
    assert result.data is None
    assert result.error is not None
    assert result.error == "Insight ins-non-existent not found"


@pytest.mark.asyncio
async def test_update_insight(mock_repository: MockRepository):
    """insightの更新をテストする"""
    insight_id = "ins-to-update"
    initial_data = {
        "insight_data": "Old insight",
        "current_insight_data": "Old current",
        "facts": "Old facts",
        "thinking": "Initial thinking",
    }
    await mock_repository.save_insight(insight_id, initial_data, "user-update")

    update_data = {
        "insight_data": "Updated insight data",  # This is the new main insight
        "current_insight_data": "Updated current data",  # This becomes the new current
        "thinking": "Updated thinking",
        "status": "SUCCESS",  # Assuming status is passed in update_data
    }
    # save_insight_update は MockRepository には直接存在しない
    # update_insight メソッドを使用する
    await mock_repository.update_insight(
        insight_id=insight_id,
        insight_data=update_data["insight_data"],
        current_insight_data=update_data["current_insight_data"],
        thinking=update_data["thinking"],
        status=update_data["status"],
        # facts は update_insight の引数にない。必要なら別途更新ロジックが必要。
    )

    result = await mock_repository.get_insight(insight_id)
    assert isinstance(result, RepositoryResult)
    assert result.data is not None
    assert result.data["insight_id"] == insight_id
    assert result.data["insight_data"] == "Updated insight data"
    assert result.data["current_insight_data"] == "Updated current data"
    assert result.data["thinking"] == "Updated thinking"
    assert result.data["status"] == "SUCCESS"
    assert result.data["facts"] == "Old facts"  # Factsは更新されていないことを確認
    assert "updated_at" in result.data


@pytest.mark.asyncio
async def test_update_insight_not_found(mock_repository: MockRepository):
    """存在しないinsightの更新をテストする"""
    # update_insightは存在しないIDの場合、エラーを発生させるか、何もしないか。
    # 現在のMockRepositoryの実装では、KeyErrorが発生すると想定される。
    with pytest.raises(KeyError):
        await mock_repository.update_insight(
            insight_id="ins-non-existent-update",
            insight_data="data",
            current_insight_data="current",
            thinking="thinking",
            status="SUCCESS",
        )


@pytest.mark.asyncio
async def test_get_insights_by_user_id(mock_repository: MockRepository):
    """ユーザーIDによるinsightのフィルタリング取得をテストする"""
    user1_id = "user1"
    user2_id = "user2"

    await mock_repository.save_insight(
        "ins1-user1", {"insight_data": "data1"}, user1_id
    )
    await mock_repository.save_insight(
        "ins2-user1", {"insight_data": "data2"}, user1_id
    )
    await mock_repository.save_insight(
        "ins1-user2", {"insight_data": "data3"}, user2_id
    )

    result_user1 = await mock_repository.get_insights_by_user_id(user1_id)
    assert isinstance(result_user1, RepositoryResult)
    assert result_user1.data is not None
    assert len(result_user1.data) == 2
    # 順序は保証されないため、IDで確認
    insight_ids_user1 = {item["insight_id"] for item in result_user1.data}
    assert "ins1-user1" in insight_ids_user1
    assert "ins2-user1" in insight_ids_user1

    result_user2 = await mock_repository.get_insights_by_user_id(user2_id)
    assert isinstance(result_user2, RepositoryResult)
    assert result_user2.data is not None
    assert len(result_user2.data) == 1
    assert result_user2.data[0]["insight_id"] == "ins1-user2"

    result_non_existent_user = await mock_repository.get_insights_by_user_id(
        "non-existent-user"
    )
    assert isinstance(result_non_existent_user, RepositoryResult)
    assert result_non_existent_user.data == []  # データがない場合は空リスト
    assert result_non_existent_user.error is None


# MockRepositoryは実際には各AgentRepositoryの基底クラスであり、
# save_suggestion, save_action, save_insightは具体的なAgentRepositoryで
# 利用されることを想定している。MockRepository自体は汎用的なデータストア。
# そのため、ここでは汎用的なデータ操作(主にget系)と、
# 各エンティティの基本的な保存・取得のテストに焦点を当てる。
