"""Authenticated source lifecycle; recorder lifecycle remains owned by Electron."""

import sqlite3
from uuid import UUID, uuid4

from pantaray_agents.local_runtime.runtime.identity import (
    verify_current_owner,
)
from pantaray_agents.local_runtime.storage.transactions import immediate_transaction
from pantaray_agents.schema.context_source import (
    SourceBinding,
    SourceBlocked,
    SourceReady,
    SourceState,
    SourceStopped,
    SourceTransition,
    SourceTransitionApplied,
    SourceTransitionBlocked,
    SourceTransitionConflict,
    SourceTransitionResult,
)

from . import store
from .source_gate import SourceGate

UNINITIALIZED_SOURCE = SourceStopped(
    kind="stopped",
    epoch=UUID(int=0),
    policy_revision="uninitialized",
    reason="disabled",
)


def _epoch(state: SourceState) -> UUID:
    return state.binding.epoch if state.kind == "ready" else state.epoch


def _policy(state: SourceState) -> str:
    return (
        state.binding.policy_revision
        if state.kind == "ready"
        else state.policy_revision
    )


class SourceControl:
    def __init__(self) -> None:
        self.gate = SourceGate()
        self._issued: dict[str, UUID] = {}

    def forget_session(self, user_id: str) -> None:
        """Invalidate session-owned permits while the caller holds gate.turn()."""
        self._issued.pop(user_id, None)
        self.gate.revoke(user_id)

    async def read(self, connection: sqlite3.Connection, user_id: str) -> SourceState:
        async with self.gate.turn():
            verify_current_owner(user_id)
            state = store.get_source(connection, user_id) or UNINITIALIZED_SOURCE
            if state.kind == "ready" and self.gate.current(user_id) is None:
                # Persisted readiness cannot authorize raw access after restart.
                return SourceStopped(
                    kind="stopped",
                    epoch=_epoch(state),
                    policy_revision=_policy(state),
                    reason="shutdown",
                )
            return state

    async def transition(
        self, connection: sqlite3.Connection, user_id: str, request: SourceTransition
    ) -> SourceTransitionResult:
        async with self.gate.turn():
            verify_current_owner(user_id)
            with immediate_transaction(connection):
                persisted = store.get_source(connection, user_id)
                current = persisted or UNINITIALIZED_SOURCE
                try:
                    receipt = store.get_source_receipt(connection, user_id, request)
                except store.ContextStoreConflict:
                    return SourceTransitionConflict(
                        kind="conflict",
                        current_epoch=_epoch(current),
                        reason="request_id_reused",
                    )
                if receipt is not None:
                    return receipt
                result = self._result(user_id, current, request)
                if result.kind == "applied":
                    store.compare_source(connection, user_id, persisted, result.state)
                store.save_source_receipt(connection, user_id, request, result)
            # No await between durable commit and permit update. A failed commit
            # leaves the old permit and issued epoch intact. Recorder lifecycle
            # changes do not revoke access to already recorded context. Activation
            # replaces the read grant only when the store identity changes.
            if result.kind == "applied" and request.kind != "set_capture_paused":
                if result.state.kind == "ready":
                    self._issued.pop(user_id, None)
                    self.gate.activate(result.state.binding)
                else:
                    self._issued[user_id] = result.state.epoch
                    if request.kind == "suspend" and request.reason == "signed_out":
                        self.gate.revoke(user_id)
            return result

    def _result(
        self, user_id: str, current: SourceState, request: SourceTransition
    ) -> SourceTransitionResult:
        epoch = _epoch(current)
        expected = (
            request.issued_epoch
            if request.kind == "activate"
            else request.expected_epoch
        )
        if expected != epoch:
            return SourceTransitionConflict(
                kind="conflict", current_epoch=epoch, reason="stale_epoch"
            )
        if request.kind == "set_capture_paused":
            if current.kind != "ready":
                return SourceTransitionBlocked(
                    kind="blocked",
                    state=SourceBlocked(
                        kind="blocked",
                        epoch=epoch,
                        policy_revision=_policy(current),
                        reason="recorder_unavailable",
                    ),
                )
            return SourceTransitionApplied(
                kind="applied",
                state=SourceReady(
                    kind="ready",
                    binding=current.binding,
                    capture_paused=request.paused,
                ),
            )
        if request.kind == "suspend":
            return SourceTransitionApplied(
                state=SourceStopped(
                    kind="stopped",
                    epoch=uuid4(),
                    policy_revision=request.policy_revision,
                    reason=request.reason,
                ),
                kind="applied",
            )
        if self._issued.get(user_id) != epoch:
            return SourceTransitionBlocked(
                kind="blocked",
                state=SourceBlocked(
                    kind="blocked",
                    epoch=epoch,
                    policy_revision=_policy(current),
                    reason="recorder_unavailable",
                ),
            )
        return SourceTransitionApplied(
            kind="applied",
            state=SourceReady(
                kind="ready",
                binding=SourceBinding(
                    user_id=user_id,
                    epoch=epoch,
                    policy_revision=_policy(current),
                    store_id=request.recorder_binding.store_id,
                    protocol_version=request.recorder_binding.protocol_version,
                ),
                capture_paused=request.capture_paused,
            ),
        )


context_source_control = SourceControl()
