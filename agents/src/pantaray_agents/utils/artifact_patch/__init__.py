"""artifact patch DSL を用いた文書更新ユーティリティ。"""

from .errors import (
    ArtifactPatchCommitError,
    ArtifactPatchConflictError,
    ArtifactPatchError,
    ArtifactPatchRepositoryError,
)
from .parser import (
    ArtifactCompletion,
    ArtifactDocumentToolOutput,
    ArtifactGenericToolCall,
    ArtifactPatch,
    parse_artifact_document_tool_call,
    parse_artifact_document_tool_output,
    parse_artifact_document_tool_payload,
)

__all__ = [
    "ArtifactCompletion",
    "ArtifactDocumentToolOutput",
    "ArtifactGenericToolCall",
    "ArtifactPatch",
    "ArtifactPatchError",
    "ArtifactPatchCommitError",
    "ArtifactPatchConflictError",
    "ArtifactPatchRepositoryError",
    "parse_artifact_document_tool_call",
    "parse_artifact_document_tool_output",
    "parse_artifact_document_tool_payload",
]
