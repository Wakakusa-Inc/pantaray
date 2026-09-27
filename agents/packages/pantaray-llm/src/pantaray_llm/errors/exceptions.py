from __future__ import annotations

from .error_contract import (
    LlmProvider,
    LlmRecoveryStrategy,
    ProxyErrorCode,
    ProxySuggestedAction,
    ToolCallViolationReason,
)


class LlmProxyExecutionError(RuntimeError):
    def __init__(
        self,
        *,
        error_code: ProxyErrorCode,
        error_message: str,
        retryable: bool,
        recovery: LlmRecoveryStrategy | None = None,
        suggested_action: ProxySuggestedAction | None = None,
        local_job_id: str | None = None,
        upstream_provider: LlmProvider | None = None,
        upstream_request_id: str | None = None,
        profile_id: str | None = None,
        upstream_status_code: int | None = None,
        upstream_code: str | None = None,
        usage_metadata: dict[str, int] | None = None,
        tool_call_violation_reason: ToolCallViolationReason | None = None,
        actual_tool_call_count: int | None = None,
        tool_name: str | None = None,
        response_status: str | None = None,
        argument_path: str | None = None,
        schema_keyword: str | None = None,
        media_failure_reason: str | None = None,
    ) -> None:
        super().__init__(error_message)
        self.error_code = error_code
        self.error_message = error_message
        self.retryable = retryable
        resolved_recovery: LlmRecoveryStrategy = recovery or (
            "retry_same_request" if retryable else "stop"
        )
        if retryable != (resolved_recovery == "retry_same_request"):
            raise ValueError(
                "retryable must match recovery=retry_same_request semantics"
            )
        self.recovery = resolved_recovery
        self.suggested_action = suggested_action
        self.local_job_id = local_job_id
        self.upstream_provider = upstream_provider
        self.upstream_request_id = upstream_request_id
        self.profile_id = profile_id
        self.upstream_status_code = upstream_status_code
        self.upstream_code = upstream_code
        self.usage_metadata = usage_metadata
        self.tool_call_violation_reason = tool_call_violation_reason
        self.actual_tool_call_count = actual_tool_call_count
        self.tool_name = tool_name
        self.response_status = response_status
        self.argument_path = argument_path
        self.schema_keyword = schema_keyword
        # The proxy's `details.reason`. The Action boundary uses it to tell an
        # oversized or undecodable image apart from a generic invalid request.
        self.media_failure_reason = media_failure_reason


__all__ = ["LlmProxyExecutionError"]
