"""utils/metrics.py のユニットテスト。

ツール実行および LLM 呼び出しのメトリクス記録関数をテストする。
"""

from __future__ import annotations

from unittest.mock import patch

from pantaray_agents.utils.metrics import (
    record_llm_call,
    record_tool_execution,
)


class TestToolExecutionMetrics:
    """ツール実行メトリクスのテスト。"""

    def test_record_tool_execution_success(self) -> None:
        """ツール実行成功時のメトリクスが記録されることを確認。"""
        with (
            patch("pantaray_agents.utils.metrics.TOOL_EXECUTIONS") as mock_executions,
            patch(
                "pantaray_agents.utils.metrics.TOOL_EXECUTION_DURATION"
            ) as mock_duration,
            patch("pantaray_agents.utils.metrics.TOOL_TOKENS_USED") as mock_tokens,
        ):
            record_tool_execution(
                tool_id="memory_search",
                status="success",
                duration_seconds=1.5,
                prompt_tokens=100,
                completion_tokens=50,
            )

            mock_executions.labels.assert_called_once_with(
                tool_id="memory_search", status="success"
            )
            mock_executions.labels.return_value.inc.assert_called_once()
            mock_duration.labels.assert_called_once_with(tool_id="memory_search")
            mock_duration.labels.return_value.observe.assert_called_once_with(1.5)
            assert mock_tokens.labels.call_count == 2

    def test_record_tool_execution_no_tokens(self) -> None:
        """トークン使用量が 0 の場合はトークンメトリクスが記録されないことを確認。"""
        with (
            patch("pantaray_agents.utils.metrics.TOOL_EXECUTIONS"),
            patch("pantaray_agents.utils.metrics.TOOL_EXECUTION_DURATION"),
            patch("pantaray_agents.utils.metrics.TOOL_TOKENS_USED") as mock_tokens,
        ):
            record_tool_execution(
                tool_id="thinking",
                status="success",
                duration_seconds=0.5,
                prompt_tokens=0,
                completion_tokens=0,
            )

            mock_tokens.labels.assert_not_called()


class TestLlmCallMetrics:
    """LLM 呼び出しメトリクスのテスト。"""

    def test_record_llm_call_success(self) -> None:
        """LLM 呼び出し成功時のメトリクスが記録されることを確認。"""
        with (
            patch("pantaray_agents.utils.metrics.LLM_CALLS") as mock_calls,
            patch("pantaray_agents.utils.metrics.LLM_CALL_DURATION") as mock_duration,
            patch("pantaray_agents.utils.metrics.LLM_TOKENS") as mock_tokens,
        ):
            record_llm_call(
                purpose="executing",
                status="success",
                duration_seconds=2.0,
                prompt_tokens=500,
                completion_tokens=200,
            )

            mock_calls.labels.assert_called_once_with(
                purpose="executing", status="success"
            )
            mock_calls.labels.return_value.inc.assert_called_once()
            mock_duration.labels.assert_called_once_with(purpose="executing")
            mock_duration.labels.return_value.observe.assert_called_once_with(2.0)
            assert mock_tokens.labels.call_count == 2

    def test_record_llm_call_error(self) -> None:
        """LLM 呼び出しエラー時のメトリクスが記録されることを確認。"""
        with (
            patch("pantaray_agents.utils.metrics.LLM_CALLS") as mock_calls,
            patch("pantaray_agents.utils.metrics.LLM_CALL_DURATION") as mock_duration,
            patch("pantaray_agents.utils.metrics.LLM_TOKENS"),
        ):
            record_llm_call(
                purpose="planning",
                status="error",
                duration_seconds=5.0,
            )

            mock_calls.labels.assert_called_once_with(
                purpose="planning", status="error"
            )
            mock_duration.labels.return_value.observe.assert_called_once_with(5.0)
