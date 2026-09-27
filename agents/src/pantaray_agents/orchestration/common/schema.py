"""オーケストレーション用の共有スキーマ定義。"""

from pydantic import BaseModel


# For JWT validation
class User(BaseModel):
    id: str
