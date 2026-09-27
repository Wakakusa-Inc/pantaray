from __future__ import annotations

import asyncio
from dataclasses import dataclass

from pantaray_agents.local_runtime.artifacts import (
    LocalTextArtifactDocument,
    ensure_local_text_artifact,
    resolve_local_text_artifact_relative_path,
    write_local_text_artifact,
)
from pantaray_agents.utils.artifact_patch.errors import ArtifactPatchConflictError

from .target import ArtifactDocumentTarget

READ_RETRY_BASE_DELAY_SECONDS = 0.2


@dataclass(frozen=True, slots=True)
class ArtifactDocumentStore:
    target: ArtifactDocumentTarget

    def ensure(
        self, user_id: str, *, initial_plaintext: str = ""
    ) -> LocalTextArtifactDocument:
        self.target.require_user_id(user_id)
        return ensure_local_text_artifact(
            kind=self.target.kind,
            template=self.target.template,
            user_id=user_id,
            initial_plaintext=initial_plaintext,
        )

    def resolve_relative_path(self, user_id: str) -> str:
        self.target.require_user_id(user_id)
        return resolve_local_text_artifact_relative_path(
            template=self.target.template,
            user_id=user_id,
        )

    async def read(self, user_id: str) -> str:
        return self.ensure(user_id).plaintext

    async def read_with_retry(self, user_id: str, max_attempts: int = 3) -> str:
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")
        for attempt in range(max_attempts):
            try:
                return await self.read(user_id)
            except (ConnectionError, TimeoutError, OSError) as exc:
                if attempt >= max_attempts - 1:
                    raise ConnectionError(self.target.read_error_message) from exc
                await asyncio.sleep(READ_RETRY_BASE_DELAY_SECONDS * (2**attempt))
        raise RuntimeError("unreachable read retry state")

    async def write(
        self,
        user_id: str,
        markdown: str,
        expected_base_sha256: str,
    ) -> tuple[str, str]:
        current_document = self.ensure(user_id)
        if current_document.sha256 != expected_base_sha256:
            raise ArtifactPatchConflictError(self.target.conflict_error_message)
        written_document = write_local_text_artifact(
            kind=self.target.kind,
            user_id=user_id,
            relative_path=current_document.relative_path,
            plaintext=markdown or "",
        )
        return written_document.relative_path, written_document.sha256

    async def rollback(self, user_id: str, storage_path: str, base_text: str) -> None:
        self.target.require_user_id(user_id)
        write_local_text_artifact(
            kind=self.target.kind,
            user_id=user_id,
            relative_path=storage_path,
            plaintext=base_text or "",
        )
