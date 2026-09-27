"""モックリポジトリクラス"""

from datetime import datetime
from typing import Any, ClassVar, TypeVar

from ..schema.repositories.repository import RepositoryResult

T = TypeVar("T")


class MockRepository:
    """モックリポジトリの基本クラス

    全てのMockRepositoryインスタンス間で共有されるグローバルデータストアを使用します。
    これにより、異なるエージェント間のデータ共有が可能になります。
    """

    # クラス変数としてグローバルデータストアを定義
    _global_data: ClassVar[dict[str, list[dict[str, Any]]]] = {}

    def __init__(self) -> None:
        """初期化"""
        # データはインスタンス変数ではなくクラス変数を参照
        if not MockRepository._global_data:  # テスト間で共有されるため、初回のみ初期化
            MockRepository._global_data["suggestions"] = []
            MockRepository._global_data["actions"] = []
            MockRepository._global_data["insights"] = []
            MockRepository._global_data["action_steps"] = []
        self.data = self._global_data

    async def save_data(self, collection: str, data: dict[str, Any]) -> None:
        """データを保存する

        Args:
            collection (str): コレクション名
            data (Dict[str, Any]): 保存するデータ
        """
        if collection not in self.data:
            self.data[collection] = []

        # IDが既に存在する場合は更新、存在しない場合は追加
        id_field = self._get_id_field_for_collection(collection)
        if id_field and id_field in data:
            # 既存のデータを探す
            existing_index = -1
            for i, item in enumerate(self.data[collection]):
                if item.get(id_field) == data[id_field]:
                    existing_index = i
                    break

            if existing_index >= 0:
                # 既存のデータを更新
                self.data[collection][existing_index] = data
                return

        # 新規データを追加
        self.data[collection].append(data)

    def _get_id_field_for_collection(self, collection: str) -> str:
        """コレクションのID項目名を取得する

        Args:
            collection (str): コレクション名

        Returns:
            str: ID項目名
        """
        collection_id_map = {
            "suggestions": "suggestion_id",
            "actions": "action_id",
            "insights": "insight_id",
            "insight_updates": "insight_update_id",
            "insight_update_runs": "insight_update_id",
        }
        return collection_id_map.get(collection, "")

    async def get_data(
        self, collection: str, id_field: str, id_value: str
    ) -> RepositoryResult[dict[str, Any]]:
        """IDに基づいてデータを取得する

        Args:
            collection (str): コレクション名
            id_field (str): ID用のフィールド名
            id_value (str): ID値

        Returns:
            RepositoryResult[dict[str, Any]]: 取得したデータを含むレスポンス
        """
        if collection not in self.data:
            return RepositoryResult(error=f"{collection} not found")

        for item in self.data[collection]:
            if item.get(id_field) == id_value:
                return RepositoryResult(data=item)

        return RepositoryResult(
            error=f"{id_field} {id_value} not found in {collection}"
        )

    async def get_latest_data(
        self, collection: str, filter_field: str, filter_value: str, limit: int = 5
    ) -> RepositoryResult[list[dict[str, Any]]]:
        """フィルタに基づいて最新のデータを取得する

        Args:
            collection (str): コレクション名
            filter_field (str): フィルタフィールド名
            filter_value (str): フィルタ値
            limit (int, optional): 取得する最大件数. デフォルトは5.

        Returns:
            RepositoryResult[list[dict[str, Any]]]: 取得したデータを含むレスポンス
        """
        if collection not in self.data:
            return RepositoryResult(error=f"{collection} not found")

        filtered_data = [
            item
            for item in self.data[collection]
            if item.get(filter_field) == filter_value
        ]

        if not filtered_data:
            return RepositoryResult(
                error=f"No data found in {collection} with {filter_field}={filter_value}"
            )

        # 作成日時でソート (最新のものが先頭)
        sorted_data = sorted(
            filtered_data,
            key=lambda x: x.get("created_at", datetime.min),
            reverse=True,
        )

        return RepositoryResult(data=sorted_data[:limit])

    @classmethod
    def clear_data(cls) -> None:
        """テスト用にグローバルデータストアをリセットする"""
        cls._global_data.clear()

    async def save_suggestion(
        self, suggestion_id: str, data: dict[str, Any], user_id: str
    ) -> None:
        """サジェスチョンを保存する"""
        record = {
            "suggestion_id": suggestion_id,
            "user_id": user_id,
            "created_at": datetime.now(),
            **data,
        }
        await self.save_data("suggestions", record)

    async def get_suggestion(
        self, suggestion_id: str
    ) -> RepositoryResult[dict[str, Any]]:
        """サジェスチョンIDに基づいてサジェスチョンを取得する"""
        result = await self.get_data("suggestions", "suggestion_id", suggestion_id)
        if result.error:
            return RepositoryResult(error=f"Suggestion {suggestion_id} not found")
        return result

    async def save_action(
        self, action_id: str, suggestion_id: str, data: dict[str, Any], user_id: str
    ) -> None:
        """アクションを保存する"""
        record = {
            "action_id": action_id,
            "suggestion_id": suggestion_id,
            "user_id": user_id,
            "created_at": datetime.now(),
            **data,
        }
        await self.save_data("actions", record)

    async def get_action(self, action_id: str) -> RepositoryResult[dict[str, Any]]:
        """アクションIDに基づいてアクションを取得する"""
        result = await self.get_data("actions", "action_id", action_id)
        if result.error:
            return RepositoryResult(error=f"Action {action_id} not found")
        return result

    async def save_insight(
        self, insight_id: str, data: dict[str, Any], user_id: str
    ) -> None:
        """インサイトを保存する"""
        record = {
            "insight_id": insight_id,
            "user_id": user_id,
            "created_at": datetime.now(),
            "updated_at": datetime.now(),  # 初期保存時もupdated_atを設定
            **data,
        }
        await self.save_data("insights", record)

    async def get_insight(self, insight_id: str) -> RepositoryResult[dict[str, Any]]:
        """インサイトIDに基づいてインサイトを取得する"""
        result = await self.get_data("insights", "insight_id", insight_id)
        if result.error:
            return RepositoryResult(error=f"Insight {insight_id} not found")
        return result

    async def update_insight(
        self,
        insight_id: str,
        insight_data: str,
        current_insight_data: str,
        thinking: str,
        status: str,
        # facts: str | None = None, # factsの更新はsave_insightで行う想定
    ) -> None:
        """インサイトを更新する"""
        if "insights" not in self.data:
            raise KeyError(
                f"Insight {insight_id} not found for update, collection missing."
            )

        for i, item in enumerate(self.data["insights"]):
            if item.get("insight_id") == insight_id:
                self.data["insights"][i]["insight_data"] = insight_data
                self.data["insights"][i]["current_insight_data"] = current_insight_data
                self.data["insights"][i]["thinking"] = thinking
                self.data["insights"][i]["status"] = status
                self.data["insights"][i]["updated_at"] = datetime.now()
                # factsの更新はここではない。save_insightで実施される想定。
                return
        raise KeyError(f"Insight {insight_id} not found for update.")

    async def get_insights_by_user_id(
        self, user_id: str
    ) -> RepositoryResult[list[dict[str, Any]]]:
        """ユーザーIDに基づいてインサイトを取得する"""
        if "insights" not in self.data:
            return RepositoryResult(data=[])  # コレクションがなければ空

        user_insights = [
            item for item in self.data["insights"] if item.get("user_id") == user_id
        ]
        return RepositoryResult(data=user_insights)
