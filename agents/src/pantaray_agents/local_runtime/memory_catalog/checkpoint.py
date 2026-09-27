from __future__ import annotations

from pantaray_agents.schema.agent.action import (
    AppliedMemoryDraftCommandCheckpoint,
    MemoryContextEpochCheckpoint,
    MemoryContextItemCheckpoint,
    MemoryDocumentCheckpoint,
    MemoryDraftCheckpointModel,
    MemoryDraftLinkCheckpoint,
)

from .draft import validate_memory_draft_checkpoint
from .models import (
    AppliedDraftCommand,
    DraftLink,
    MemoryContextEpoch,
    MemoryContextItem,
    MemoryDocument,
    MemoryDraftCheckpoint,
    ResolvedContextItem,
)


def serialize_memory_draft(
    draft: MemoryDraftCheckpoint,
) -> MemoryDraftCheckpointModel:
    validate_memory_draft_checkpoint(draft)
    return MemoryDraftCheckpointModel(
        draft_session_id=draft.draft_session_id,
        user_id=draft.user_id,
        owner_node_id=draft.owner_node_id,
        base_revision_id=draft.base_revision_id,
        draft_revision=draft.draft_revision,
        documents=[
            MemoryDocumentCheckpoint(source_path=item.source_path, content=item.content)
            for item in draft.documents
        ],
        links=[
            MemoryDraftLinkCheckpoint(
                local_ref_id=item.local_ref_id,
                target_fragment_id=item.target_fragment_id,
                source_path=item.source_path,
                source_anchor_text=item.source_anchor_text,
                source_anchor_occurrence=item.source_anchor_occurrence,
                reference_note=item.reference_note,
                created_at=item.created_at,
                state=item.state,
            )
            for item in draft.links
        ],
        applied_commands=[
            AppliedMemoryDraftCommandCheckpoint(
                tool_invocation_id=item.tool_invocation_id,
                local_ref_id=item.local_ref_id,
                draft_revision=item.draft_revision,
            )
            for item in draft.applied_commands
        ],
    )


def deserialize_memory_draft(
    model: MemoryDraftCheckpointModel,
) -> MemoryDraftCheckpoint:
    draft = MemoryDraftCheckpoint(
        draft_session_id=model.draft_session_id,
        user_id=model.user_id,
        owner_node_id=model.owner_node_id,
        base_revision_id=model.base_revision_id,
        draft_revision=model.draft_revision,
        documents=tuple(
            MemoryDocument(source_path=item.source_path, content=item.content)
            for item in model.documents
        ),
        links=tuple(
            DraftLink(
                local_ref_id=item.local_ref_id,
                target_fragment_id=item.target_fragment_id,
                source_path=item.source_path,
                source_anchor_text=item.source_anchor_text,
                source_anchor_occurrence=item.source_anchor_occurrence,
                reference_note=item.reference_note,
                created_at=item.created_at,
                state=item.state,
            )
            for item in model.links
        ),
        applied_commands=tuple(
            AppliedDraftCommand(
                tool_invocation_id=item.tool_invocation_id,
                local_ref_id=item.local_ref_id,
                draft_revision=item.draft_revision,
            )
            for item in model.applied_commands
        ),
    )
    validate_memory_draft_checkpoint(draft)
    return draft


def serialize_memory_epoch(epoch: MemoryContextEpoch) -> MemoryContextEpochCheckpoint:
    return MemoryContextEpochCheckpoint(
        epoch_id=epoch.epoch_id,
        run_id=epoch.run_id,
        user_id=epoch.user_id,
        items=[
            MemoryContextItemCheckpoint(
                context_handle=item.item.context_handle,
                source=item.item.source,
                label=item.item.label,
                source_path=item.item.source_path,
                heading_path=item.item.heading_path,
                content=item.item.content,
                observed_at=item.item.observed_at,
                user_id=item.user_id,
                fragment_id=item.fragment_id,
                revision_id=item.revision_id,
                node_id=item.node_id,
                reference_depth=item.reference_depth,
            )
            for item in epoch.items
        ],
    )


def deserialize_memory_epoch(
    model: MemoryContextEpochCheckpoint,
) -> MemoryContextEpoch:
    return MemoryContextEpoch(
        epoch_id=model.epoch_id,
        run_id=model.run_id,
        user_id=model.user_id,
        items=tuple(
            ResolvedContextItem(
                item=MemoryContextItem(
                    context_handle=item.context_handle,
                    source=item.source,
                    label=item.label,
                    source_path=item.source_path,
                    heading_path=item.heading_path,
                    content=item.content,
                    observed_at=item.observed_at,
                ),
                user_id=item.user_id,
                fragment_id=item.fragment_id,
                revision_id=item.revision_id,
                node_id=item.node_id,
                reference_depth=item.reference_depth,
            )
            for item in model.items
        ),
    )
