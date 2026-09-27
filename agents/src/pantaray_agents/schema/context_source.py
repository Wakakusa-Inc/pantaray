"""Wire contract for the app-owned recorder's local control boundary.

The authenticated route owns the subject. Requests identify the recorder, never
an executable, configuration path, store path, or credential. P03 owns source
generation transitions; this module validates their external shapes only.
"""

from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

SourceIdentifier = Annotated[str, Field(strict=True, min_length=1, max_length=256)]
SourceStopReason = Literal["disabled", "signed_out", "policy_change", "shutdown"]
SourceBlockedReason = Literal[
    "permission_required",
    "key_unavailable",
    "recorder_unavailable",
    "protocol_incompatible",
]


class ContextSourceContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class RecorderBinding(ContextSourceContract):
    store_id: SourceIdentifier
    protocol_version: Annotated[int, Field(strict=True, ge=1, le=1)]


class SourceBinding(RecorderBinding):
    user_id: SourceIdentifier
    epoch: UUID
    policy_revision: SourceIdentifier


class SourceStopped(ContextSourceContract):
    kind: Literal["stopped"]
    epoch: UUID
    policy_revision: SourceIdentifier
    reason: SourceStopReason


class SourceStarting(ContextSourceContract):
    kind: Literal["starting"]
    epoch: UUID
    policy_revision: SourceIdentifier


class SourceReady(ContextSourceContract):
    kind: Literal["ready"]
    binding: SourceBinding
    capture_paused: bool = Field(
        default=False,
        description="Recording is turned off: the recorder keeps its permit so what "
        "it already recorded stays readable, and captures nothing new.",
    )


class SourceBlocked(ContextSourceContract):
    kind: Literal["blocked"]
    epoch: UUID
    policy_revision: SourceIdentifier
    reason: SourceBlockedReason


type SourceState = Annotated[
    SourceStopped | SourceStarting | SourceReady | SourceBlocked,
    Field(discriminator="kind"),
]


class SuspendSource(ContextSourceContract):
    kind: Literal["suspend"]
    request_id: UUID
    expected_epoch: UUID
    reason: SourceStopReason
    policy_revision: SourceIdentifier


class ActivateSource(ContextSourceContract):
    kind: Literal["activate"]
    request_id: UUID
    issued_epoch: UUID = Field(
        description="Epoch issued by the preceding suspend; must match the current epoch. "
        "Activation does not create a new epoch."
    )
    recorder_binding: RecorderBinding
    capture_paused: bool = Field(
        default=False,
        description="Restores a recorder for a user who has recording turned off: the "
        "source becomes ready and paused in one transition, so no moment exists in "
        "which concurrent work reads it as capturing. Defaults to false for receipts "
        "persisted before the field existed; the app always states it.",
    )


class SetCapturePaused(ContextSourceContract):
    """Turn capture off or on without ending the source generation.

    The epoch, the recorder binding and the read permit all stay, so reads of
    what the recorder already stored keep working while capture is paused.
    """

    kind: Literal["set_capture_paused"]
    request_id: UUID
    expected_epoch: UUID
    paused: bool


type SourceTransition = Annotated[
    SuspendSource | ActivateSource | SetCapturePaused, Field(discriminator="kind")
]


class SourceTransitionApplied(ContextSourceContract):
    kind: Literal["applied"]
    state: Annotated[
        SourceStopped | SourceStarting | SourceReady, Field(discriminator="kind")
    ]


class SourceTransitionConflict(ContextSourceContract):
    kind: Literal["conflict"]
    current_epoch: UUID
    reason: Literal["stale_epoch", "request_id_reused"]


class SourceTransitionBlocked(ContextSourceContract):
    kind: Literal["blocked"]
    state: SourceBlocked


type SourceTransitionResult = Annotated[
    SourceTransitionApplied | SourceTransitionConflict | SourceTransitionBlocked,
    Field(discriminator="kind"),
]
