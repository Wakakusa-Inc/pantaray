"""Action relay process/session ownership helpers."""

from __future__ import annotations


class ActionRelayProcessMixin:
    def _bind_action_process(
        self,
        process_id: str,
        suggestion_id: str | None,
        action_id: str,
    ) -> None:
        self._action_processes.add(process_id)
        self._process_metadata[process_id] = {
            "kind": "action",
            "suggestion_id": suggestion_id,
            "action_id": action_id,
        }

    def _release_action_process(
        self,
        process_id: str,
    ) -> None:
        try:
            task_key = f"action_event_forwarder:{process_id}"
            supervisor = getattr(self, "_task_supervisor", None)
            if supervisor is not None:
                supervisor.cancel(task_key)
        except Exception:
            pass
        if process_id in self._action_processes:
            self._action_processes.remove(process_id)
        self._process_metadata.pop(process_id, None)
