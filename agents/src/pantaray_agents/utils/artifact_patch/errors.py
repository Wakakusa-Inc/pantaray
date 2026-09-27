"""artifact_patch ループにおける例外型。

目的:
- 失敗の種類（LLM/パース/適用/永続化）を上位（Agent.process）で分類しやすくする。
- 文字列マッチングの ad-hoc を避け、型で分岐できるようにする。
"""


class ArtifactPatchError(RuntimeError):
    """artifact_patch 系の基底例外。"""


class ArtifactPatchCommitError(ArtifactPatchError):
    """永続化（Storage/DB）フェーズで失敗した場合の例外。"""


class ArtifactPatchRepositoryError(ArtifactPatchCommitError):
    """DB 更新など Repository 起因の永続化失敗。"""


class ArtifactPatchTerminalError(ArtifactPatchError):
    """artifact_patch ループを即中断すべき（リトライ無効な）失敗を表す例外。"""


class ArtifactPatchConflictError(ArtifactPatchTerminalError):
    """競合（衝突）により patch-base が古くなった場合の例外。

    例:
        - Storage の本文が、patch-base を読み取った後に別プロセスで更新された。
        - 楽観ロック（sha256一致確認）が失敗した。
    """
