from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from pathlib import Path


class ActionSubagentResourceIdentityError(ValueError):
    """A canonical resource identity is malformed."""


@dataclass(frozen=True, slots=True)
class WorkspaceResourceIdentity:
    manifest_id: str
    normalized_key: str

    def __post_init__(self) -> None:
        path = Path(self.normalized_key)
        if not self.manifest_id.strip():
            raise ActionSubagentResourceIdentityError("manifest_id must not be blank")
        if (
            not self.normalized_key.strip()
            or path.anchor != "/"
            or ".." in path.parts
            or path.as_posix() != self.normalized_key
        ):
            raise ActionSubagentResourceIdentityError(
                "workspace resource key must be a canonical absolute path"
            )

    @classmethod
    def from_resolved_path(
        cls, *, manifest_id: str, resolved_path: Path
    ) -> WorkspaceResourceIdentity:
        return cls(
            manifest_id=manifest_id,
            normalized_key=normalize_workspace_resource_key(resolved_path),
        )


@dataclass(frozen=True, slots=True)
class ExternalResourceIdentity:
    root_identity: str
    normalized_key: str

    def __post_init__(self) -> None:
        if not self.root_identity.strip() or not self.normalized_key.strip():
            raise ActionSubagentResourceIdentityError(
                "external resource identity must not be blank"
            )


type CanonicalResourceIdentity = WorkspaceResourceIdentity | ExternalResourceIdentity


def normalize_workspace_resource_key(path: Path) -> str:
    """Keep an already-resolved absolute path usable by broker capabilities."""

    if not path.is_absolute():
        raise ActionSubagentResourceIdentityError(
            "workspace resource path must be resolved and absolute"
        )
    return path.as_posix()


def resource_identities_overlap(
    left: CanonicalResourceIdentity,
    right: CanonicalResourceIdentity,
) -> bool:
    if type(left) is not type(right):
        return False
    if isinstance(left, ExternalResourceIdentity):
        assert isinstance(right, ExternalResourceIdentity)
        return (
            left.root_identity == right.root_identity
            and left.normalized_key == right.normalized_key
        )
    assert isinstance(right, WorkspaceResourceIdentity)
    if left.manifest_id != right.manifest_id:
        return False
    left_path = _workspace_collision_path(left)
    right_path = _workspace_collision_path(right)
    return left_path.is_relative_to(right_path) or right_path.is_relative_to(left_path)


def resource_is_within(
    resource: CanonicalResourceIdentity,
    claim: CanonicalResourceIdentity,
) -> bool:
    if type(resource) is not type(claim):
        return False
    if isinstance(resource, ExternalResourceIdentity):
        assert isinstance(claim, ExternalResourceIdentity)
        return resource == claim
    assert isinstance(resource, WorkspaceResourceIdentity)
    assert isinstance(claim, WorkspaceResourceIdentity)
    return resource.manifest_id == claim.manifest_id and Path(
        resource.normalized_key
    ).is_relative_to(Path(claim.normalized_key))


def workspace_intersection(
    candidate: WorkspaceResourceIdentity,
    claim: WorkspaceResourceIdentity,
) -> WorkspaceResourceIdentity | None:
    if candidate.manifest_id != claim.manifest_id:
        return None
    candidate_path = Path(candidate.normalized_key)
    claim_path = Path(claim.normalized_key)
    if candidate_path.is_relative_to(claim_path):
        return candidate
    if claim_path.is_relative_to(candidate_path):
        return claim
    return None


def _workspace_collision_path(resource: WorkspaceResourceIdentity) -> Path:
    return Path(unicodedata.normalize("NFC", resource.normalized_key.casefold()))
