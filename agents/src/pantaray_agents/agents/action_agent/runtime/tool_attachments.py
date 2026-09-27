"""Typed tool attachments carried outside prompt text."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, NotRequired, TypedDict

from pantaray_agents.agents.core.llm_file_inputs import (
    TOOL_ATTACHMENT_REF_PREFIX,
    USER_ATTACHMENT_REF_PREFIX,
    LlmFileInput,
    LocalImageLlmFileInput,
    WorkspaceLlmFileInput,
)
from pantaray_agents.schema.agent.base import JSONValue


class _CommonToolAttachment(TypedDict):
    type: Literal["file"]
    ref: str
    blob_ref: str
    display_path: str
    mime_type: str
    byte_size: int
    sha256: str


class WorkspaceToolAttachment(_CommonToolAttachment):
    source_kind: Literal["workspace_file"]
    workspace_root_path: str
    workspace_relative_path: str


class LocalImageAttachment(_CommonToolAttachment):
    """A user-scoped local image artifact carried alongside a history entry."""

    source_kind: Literal["local_image_blob"]
    storage_path: str


type ToolAttachment = WorkspaceToolAttachment | LocalImageAttachment
_ATTACHMENT_REF_PREFIXES = (TOOL_ATTACHMENT_REF_PREFIX, USER_ATTACHMENT_REF_PREFIX)


class ToolAttachmentOwner(TypedDict, total=False):
    attachments: NotRequired[list[ToolAttachment]]


def coerce_tool_attachments(value: object) -> list[ToolAttachment]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes | bytearray):
        return []
    attachments: list[ToolAttachment] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        attachment = _coerce_tool_attachment(item)
        if attachment is not None:
            attachments.append(attachment)
    return attachments


def collect_prompt_file_inputs(
    *,
    prompt: str,
    owners: Sequence[Mapping[str, object]],
) -> list[LlmFileInput]:
    by_ref: dict[str, ToolAttachment] = {}
    for owner in owners:
        for attachment in coerce_tool_attachments(owner.get("attachments")):
            by_ref.setdefault(attachment["ref"], attachment)

    ordered_refs = sorted(
        (ref for ref in by_ref if ref in prompt),
        key=lambda ref: prompt.find(ref),
    )
    return [_to_llm_file_input(by_ref[ref]) for ref in ordered_refs]


def collect_state_prompt_file_inputs(
    *,
    state: Mapping[str, object],
    prompt: str,
    scope_handles: Sequence[str],
) -> list[LlmFileInput]:
    owners: list[Mapping[str, object]] = []
    history_by_scope = state.get("history_by_scope")
    if isinstance(history_by_scope, Mapping):
        for scope_handle in scope_handles:
            raw_history = history_by_scope.get(scope_handle)
            if isinstance(raw_history, Sequence) and not isinstance(raw_history, str):
                owners.extend(item for item in raw_history if isinstance(item, Mapping))

    return collect_prompt_file_inputs(prompt=prompt, owners=owners)


def attachment_refs_for_output(output: JSONValue) -> tuple[str, ...]:
    if not isinstance(output, Mapping):
        return ()
    attachments = output.get("attachments")
    if not isinstance(attachments, Sequence) or isinstance(attachments, str):
        return ()
    refs: list[str] = []
    for item in attachments:
        if not isinstance(item, Mapping):
            continue
        ref = item.get("ref")
        if isinstance(ref, str) and ref.startswith(TOOL_ATTACHMENT_REF_PREFIX):
            refs.append(ref)
    return tuple(refs)


def _coerce_tool_attachment(item: Mapping[object, object]) -> ToolAttachment | None:
    type_value = item.get("type")
    source_kind = item.get("source_kind")
    ref = item.get("ref")
    blob_ref = item.get("blob_ref")
    display_path = item.get("display_path")
    mime_type = item.get("mime_type")
    byte_size = item.get("byte_size")
    sha256 = item.get("sha256")
    if (
        type_value != "file"
        or source_kind not in ("workspace_file", "local_image_blob")
        or not isinstance(ref, str)
        or not ref.startswith(_ATTACHMENT_REF_PREFIXES)
        or not isinstance(blob_ref, str)
        or not isinstance(display_path, str)
        or not isinstance(mime_type, str)
        or not isinstance(byte_size, int)
        or not isinstance(sha256, str)
    ):
        return None
    common: _CommonToolAttachment = {
        "type": "file",
        "ref": ref,
        "blob_ref": blob_ref,
        "display_path": display_path,
        "mime_type": mime_type,
        "byte_size": byte_size,
        "sha256": sha256,
    }
    if source_kind == "local_image_blob":
        storage_path = item.get("storage_path")
        if not isinstance(storage_path, str):
            return None
        return {
            **common,
            "source_kind": "local_image_blob",
            "storage_path": storage_path,
        }
    workspace_root_path = item.get("workspace_root_path")
    workspace_relative_path = item.get("workspace_relative_path")
    if not isinstance(workspace_root_path, str) or not isinstance(
        workspace_relative_path, str
    ):
        return None
    return {
        **common,
        "source_kind": "workspace_file",
        "workspace_root_path": workspace_root_path,
        "workspace_relative_path": workspace_relative_path,
    }


def _to_llm_file_input(attachment: ToolAttachment) -> LlmFileInput:
    if attachment["source_kind"] == "local_image_blob":
        local_image_input: LocalImageLlmFileInput = {
            "ref": attachment["ref"],
            "blob_ref": attachment["blob_ref"],
            "mime_type": attachment["mime_type"],
            "byte_size": attachment["byte_size"],
            "sha256": attachment["sha256"],
            "source_kind": "local_image_blob",
            "storage_path": attachment["storage_path"],
        }
        return local_image_input
    workspace_input: WorkspaceLlmFileInput = {
        "ref": attachment["ref"],
        "blob_ref": attachment["blob_ref"],
        "mime_type": attachment["mime_type"],
        "byte_size": attachment["byte_size"],
        "sha256": attachment["sha256"],
        "source_kind": "workspace_file",
        "workspace_root_path": attachment["workspace_root_path"],
        "workspace_relative_path": attachment["workspace_relative_path"],
    }
    return workspace_input


__all__ = [
    "LocalImageAttachment",
    "ToolAttachment",
    "ToolAttachmentOwner",
    "attachment_refs_for_output",
    "coerce_tool_attachments",
    "collect_prompt_file_inputs",
    "collect_state_prompt_file_inputs",
]
