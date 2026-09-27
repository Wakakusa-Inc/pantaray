"""Prometheus 互換のメトリクス公開ヘルパー。"""

from __future__ import annotations

from typing import Literal

from fastapi import FastAPI, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
)

WS_RESUME_REQUESTED = Counter(
    "ws_resume_requested_total",
    "Number of resume_session requests grouped by kind",
    ["kind"],
)
WS_RESUME_SUCCEEDED = Counter(
    "ws_resume_succeeded_total",
    "Number of successful resume_session grouped by kind",
    ["kind"],
)
WS_RESUME_EXPIRED = Counter(
    "ws_resume_expired_total",
    "Number of resume_session failures grouped by reason and kind",
    ["reason", "kind"],
)
WS_RESUME_INVALID_CURSOR = Counter(
    "ws_resume_invalid_cursor_total",
    "Number of resume_session failures caused by invalid cursor",
)
WS_RESUME_TOO_MANY_MISSING_CHUNKS = Counter(
    "ws_resume_too_many_missing_chunks_total",
    "Number of resume_session failures caused by too many missing chunks",
)
WS_RESUME_MISSING_CHUNKS_COUNT = Histogram(
    "ws_resume_missing_chunks_count",
    "Missing chunk count observed in session_resumed responses",
    buckets=(0, 1, 2, 3, 5, 10, 25, 50, 100, 250, 500, 1000, 2000, 5000, float("inf")),
)

WS_DEPENDENCY_FAIL = Counter(
    "ws_dependency_fail_total",
    "Number of dependency failures inside WS handler grouped by dependency and operation",
    ["dependency", "operation"],
)
WS_DEPENDENCY_CIRCUIT_OPEN = Counter(
    "ws_dependency_circuit_open_total",
    "Number of circuit breaker opens grouped by dependency",
    ["dependency"],
)

ACTION_JOBS_ENQUEUED = Counter(
    "action_jobs_enqueued_total",
    "Number of ActionAgent jobs enqueued",
)
ACTION_JOBS_COMPLETED = Counter(
    "action_jobs_completed_total",
    "Number of ActionAgent jobs completed grouped by status",
    ["status"],
)
ACTION_JOBS_ACTIVE = Gauge(
    "action_jobs_active",
    "Active ActionAgent jobs currently running",
)
ACTION_START_LEASE_CONTENTION = Counter(
    "action_start_lease_contention_total",
    "Number of Action start lease contention events",
)
ACTION_PROCESS_STARTED_REPLAY = Counter(
    "action_process_started_replay_total",
    "Number of Action process_started replay events emitted",
)
ACTION_REPLAY_LIVE_ATTACH_FAILED = Counter(
    "action_replay_live_attach_failed_total",
    "Number of Action live attach failures during replay grouped by path and reason",
    ["path", "reason"],
)
ACTION_EVENTS_SENT = Counter(
    "action_events_sent_total",
    "Number of ActionAgent WS events sent grouped by type",
    ["event"],
)
ACTION_EVENTS_ACKED = Counter(
    "action_events_acked_total",
    "Number of ActionAgent WS events acknowledged grouped by type",
    ["event"],
)
SUGGESTION_EVENTS_SENT = Counter(
    "suggestion_events_sent_total",
    "Number of SuggestionAgent WS events sent grouped by type",
    ["event"],
)
SUGGESTION_EVENTS_ACKED = Counter(
    "suggestion_events_acked_total",
    "Number of SuggestionAgent WS events acknowledged grouped by type",
    ["event"],
)

# ActionAgent 向けメトリクス
ACTION_AGENT_MESSAGES = Counter(
    "action_agent_messages_total",
    "Number of validated Supervisor and Goal Worker message transition attempts",
    ["direction"],
)
ACTION_AGENT_GOAL_COMPLETION_REVIEWS = Counter(
    "action_agent_goal_completion_reviews_total",
    "Number of validated Goal completion review attempts grouped by decision",
    ["decision"],
)

# ツール実行メトリクス
TOOL_EXECUTIONS = Counter(
    "tool_executions_total",
    "Number of tool executions grouped by tool_id and status",
    ["tool_id", "status"],
)
TOOL_EXECUTION_DURATION = Histogram(
    "tool_execution_duration_seconds",
    "Duration of tool executions in seconds grouped by tool_id",
    ["tool_id"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
)
TOOL_TOKENS_USED = Counter(
    "tool_tokens_used_total",
    "Total tokens used by tool executions grouped by tool_id and token_type",
    ["tool_id", "token_type"],
)

# LLM 呼び出しメトリクス
LLM_CALLS = Counter(
    "llm_calls_total",
    "Number of LLM API calls grouped by purpose and status",
    ["purpose", "status"],
)
LLM_CALL_DURATION = Histogram(
    "llm_call_duration_seconds",
    "Duration of LLM API calls in seconds grouped by purpose",
    ["purpose"],
    buckets=(0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0, float("inf")),
)
LLM_TOKENS = Counter(
    "llm_tokens_total",
    "Total tokens used by LLM calls grouped by purpose and token_type",
    ["purpose", "token_type"],
)


def record_action_job_enqueued() -> None:
    ACTION_JOBS_ENQUEUED.inc()
    ACTION_JOBS_ACTIVE.inc()


def record_action_job_completed(
    status: Literal["success", "error", "timeout", "canceled", "abandoned"],
) -> None:
    ACTION_JOBS_COMPLETED.labels(status=status).inc()
    ACTION_JOBS_ACTIVE.dec()


def record_action_event_sent(event: str) -> None:
    ACTION_EVENTS_SENT.labels(event=event).inc()


def record_action_start_lease_contention() -> None:
    ACTION_START_LEASE_CONTENTION.inc()


def record_action_process_started_replay() -> None:
    ACTION_PROCESS_STARTED_REPLAY.inc()


def record_action_replay_live_attach_failed(
    *,
    path: Literal["processing_replay", "resume_session"],
    reason: Literal["missing_fields", "attach_failed"],
) -> None:
    ACTION_REPLAY_LIVE_ATTACH_FAILED.labels(path=path, reason=reason).inc()


def record_action_event_acked(event: str) -> None:
    ACTION_EVENTS_ACKED.labels(event=event).inc()


def record_suggestion_event_sent(event: str) -> None:
    SUGGESTION_EVENTS_SENT.labels(event=event).inc()


def record_suggestion_event_acked(event: str) -> None:
    SUGGESTION_EVENTS_ACKED.labels(event=event).inc()


def record_ws_resume_requested(kind: str) -> None:
    """resume_session のリクエスト数を記録する。"""

    WS_RESUME_REQUESTED.labels(kind=kind).inc()


def record_ws_resume_succeeded(kind: str, *, missing_chunks_count: int) -> None:
    """resume_session の成功数と欠落チャンク数を記録する。"""

    WS_RESUME_SUCCEEDED.labels(kind=kind).inc()
    if missing_chunks_count >= 0:
        WS_RESUME_MISSING_CHUNKS_COUNT.observe(float(missing_chunks_count))


def record_ws_resume_expired(kind: str, *, reason: str) -> None:
    """resume_session の失敗（session_expired）数を記録する。"""

    WS_RESUME_EXPIRED.labels(reason=reason, kind=kind).inc()


def record_ws_resume_invalid_cursor() -> None:
    """resume_session の invalid cursor エラー数を記録する。"""

    WS_RESUME_INVALID_CURSOR.inc()


def record_ws_resume_too_many_missing_chunks() -> None:
    """resume_session の missing_chunks 過多エラー数を記録する。"""

    WS_RESUME_TOO_MANY_MISSING_CHUNKS.inc()


def record_ws_dependency_fail(
    *, dependency: str, operation: str, count: int = 1
) -> None:
    """WS ハンドラ内依存失敗数を記録する。"""

    if count <= 0:
        return
    WS_DEPENDENCY_FAIL.labels(dependency=dependency, operation=operation).inc(count)


def record_ws_dependency_circuit_open(*, dependency: str) -> None:
    """circuit breaker open を記録する。"""

    WS_DEPENDENCY_CIRCUIT_OPEN.labels(dependency=dependency).inc()


def record_action_agent_message(
    direction: Literal["supervisor_to_worker", "worker_to_supervisor"],
) -> None:
    ACTION_AGENT_MESSAGES.labels(direction=direction).inc()


def record_goal_completion_review(decision: Literal["accept", "revise"]) -> None:
    ACTION_AGENT_GOAL_COMPLETION_REVIEWS.labels(decision=decision).inc()


def record_tool_execution(
    tool_id: str,
    status: Literal["success", "error"],
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """ツール実行のメトリクスを記録する。

    Args:
        tool_id: 実行されたツールの ID
        status: 実行ステータス（success/error）
        duration_seconds: 実行時間（秒）
        prompt_tokens: 使用したプロンプトトークン数
        completion_tokens: 使用した完了トークン数
    """
    TOOL_EXECUTIONS.labels(tool_id=tool_id, status=status).inc()
    TOOL_EXECUTION_DURATION.labels(tool_id=tool_id).observe(duration_seconds)
    if prompt_tokens > 0:
        TOOL_TOKENS_USED.labels(tool_id=tool_id, token_type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        TOOL_TOKENS_USED.labels(tool_id=tool_id, token_type="completion").inc(
            completion_tokens
        )


def record_llm_call(
    purpose: str,
    status: Literal["success", "error"],
    duration_seconds: float,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
) -> None:
    """LLM 呼び出しのメトリクスを記録する。

    Args:
        purpose: 呼び出しの目的（例: executing, planning）
        status: 実行ステータス（success/error）
        duration_seconds: 実行時間（秒）
        prompt_tokens: 使用したプロンプトトークン数
        completion_tokens: 使用した完了トークン数
    """
    LLM_CALLS.labels(purpose=purpose, status=status).inc()
    LLM_CALL_DURATION.labels(purpose=purpose).observe(duration_seconds)
    if prompt_tokens > 0:
        LLM_TOKENS.labels(purpose=purpose, token_type="prompt").inc(prompt_tokens)
    if completion_tokens > 0:
        LLM_TOKENS.labels(purpose=purpose, token_type="completion").inc(
            completion_tokens
        )


def install_metrics_endpoint(app: FastAPI) -> None:
    """Expose /metrics endpoint compatible with Prometheus."""

    @app.get("/metrics", include_in_schema=False)
    async def metrics_endpoint() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)


__all__ = [
    "install_metrics_endpoint",
    "record_action_job_enqueued",
    "record_action_job_completed",
    "record_action_event_sent",
    "record_action_event_acked",
    "record_suggestion_event_sent",
    "record_suggestion_event_acked",
    "record_ws_resume_requested",
    "record_ws_resume_succeeded",
    "record_ws_resume_expired",
    "record_ws_resume_invalid_cursor",
    "record_ws_resume_too_many_missing_chunks",
    "record_ws_dependency_fail",
    "record_ws_dependency_circuit_open",
    "record_action_agent_message",
    "record_goal_completion_review",
    "record_tool_execution",
    "record_llm_call",
]
