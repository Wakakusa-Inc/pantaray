"""Local runtime の公開アクセスポイント。"""

from importlib import import_module

_MODULE_BY_EXPORT = {
    "append_local_process_event": ".process_events",
    "build_action_job_payload": ".job_payload_builder",
    "build_default_local_worker_specs": ".local_worker",
    "build_local_action_enqueue_request": ".action_queue",
    "build_local_suggestion_enqueue_request": ".suggestion_queue",
    "claim_next_pending_action_job": ".job_queue_runtime",
    "claim_next_pending_job": ".job_claim",
    "submit_action_message": ".action_messages",
    "dispatch_claimed_job": ".job_dispatch",
    "drain_local_jobs": ".local_worker",
    "enqueue_local_job": ".job_enqueue",
    "finalize_local_action_job": ".job_queue_runtime",
    "finalize_local_job": ".job_claim",
    "has_pending_action_job": ".job_queue_runtime",
    "has_pending_job": ".job_claim",
    "is_local_runtime_enabled": ".bootstrap",
    "LocalJobHandler": ".job_dispatch",
    "LocalWorkerSpec": ".local_worker",
    "parse_action_job_payload_json": ".job_payload_models",
    "parse_suggestion_job_payload_json": ".job_payload_models",
    "peek_next_pending_job_type": ".job_claim",
    "read_local_process_events_after": ".process_events",
    "run_local_periodic_reaper_once": ".reaper",
    "run_next_local_action_job": ".local_worker",
    "run_next_local_job": ".local_worker",
    "start_local_runtime_if_enabled": ".lifecycle",
    "stop_local_action_worker_daemon": ".worker_daemon",
    "stop_local_runtime_if_enabled": ".lifecycle",
}

__all__ = list(_MODULE_BY_EXPORT)


def __getattr__(name: str) -> object:
    module_name = _MODULE_BY_EXPORT.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(module_name, __name__)
    return getattr(module, name)
