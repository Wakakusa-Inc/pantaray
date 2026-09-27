"""モックリポジトリのテスト用ヘルパークラス"""


class RepositorySuccess[T]:
    """レポジトリ成功レスポンスのヘルパークラス"""

    def __init__(self, data: T | None = None) -> None:
        """初期化

        Args:
            data (T, optional): 成功レスポンスのデータ. デフォルトはNone.
        """
        self.data = data
        self.success = True
        self.error = None


class RepositoryError:
    """レポジトリエラーレスポンスのヘルパークラス"""

    def __init__(self, message: str, error_type: str = "db_error") -> None:
        """初期化

        Args:
            message (str): エラーメッセージ
            error_type (str, optional): エラータイプ. デフォルトは"db_error".
        """
        self.message = message
        self.error_type = error_type
        self.success = False
        self.error = self  # エラーオブジェクト自身をerrorプロパティとして持つ
        self.data = None
