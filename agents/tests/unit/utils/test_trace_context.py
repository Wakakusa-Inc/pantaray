"""utils/trace_context.py のユニットテスト。

トレースコンテキスト管理のテスト。
"""

from __future__ import annotations

import logging

from pantaray_agents.utils.trace_context import (
    TraceContext,
    TraceContextFilter,
    TraceContextManager,
    get_trace_context,
    set_trace_context,
)


class TestTraceContext:
    """TraceContext データクラスのテスト。"""

    def test_to_dict_excludes_none_values(self) -> None:
        """None 値は辞書に含まれないことを確認。"""
        ctx = TraceContext(action_id="test-action")
        result = ctx.to_dict()

        assert result == {"action_id": "test-action"}
        assert "goal_uuid" not in result
        assert "requirement_uuid" not in result

    def test_to_dict_includes_all_set_values(self) -> None:
        """設定された値はすべて辞書に含まれることを確認。"""
        ctx = TraceContext(
            action_id="test-action",
            local_job_id="job-1",
            goal_handle="G1",
            user_id="user-123",
        )
        result = ctx.to_dict()

        assert result == {
            "action_id": "test-action",
            "local_job_id": "job-1",
            "goal_handle": "G1",
            "user_id": "user-123",
        }

    def test_to_dict_includes_extra(self) -> None:
        """extra フィールドも辞書に含まれることを確認。"""
        ctx = TraceContext(
            action_id="test-action",
            extra={"custom_key": "custom_value"},
        )
        result = ctx.to_dict()

        assert result == {
            "action_id": "test-action",
            "custom_key": "custom_value",
        }

    def test_copy_creates_new_instance(self) -> None:
        """copy メソッドが新しいインスタンスを生成することを確認。"""
        original = TraceContext(action_id="original")
        copied = original.copy(goal_handle="G1")

        assert copied is not original
        assert copied.action_id == "original"
        assert copied.goal_handle == "G1"
        assert original.goal_handle is None


class TestTraceContextManager:
    """TraceContextManager のテスト。"""

    def test_sets_context_on_enter(self) -> None:
        """コンテキストに入るとトレースコンテキストが設定されることを確認。"""
        # 事前にコンテキストをクリア
        set_trace_context(None)

        with TraceContextManager(action_id="test-action", goal_handle="G1"):
            ctx = get_trace_context()
            assert ctx is not None
            assert ctx.action_id == "test-action"
            assert ctx.goal_handle == "G1"

    def test_restores_context_on_exit(self) -> None:
        """コンテキストから出ると元のコンテキストに戻ることを確認。"""
        set_trace_context(None)

        with TraceContextManager(action_id="outer"):
            with TraceContextManager(goal_handle="G1"):
                ctx = get_trace_context()
                assert ctx is not None
                assert ctx.action_id == "outer"
                assert ctx.goal_handle == "G1"

            # 内側のコンテキストを抜けたら goal_handle は None に戻る
            ctx = get_trace_context()
            assert ctx is not None
            assert ctx.action_id == "outer"
            assert ctx.goal_handle is None

        # 外側のコンテキストも抜けたら None に戻る
        assert get_trace_context() is None

    def test_merges_with_existing_context(self) -> None:
        """既存のコンテキストとマージされることを確認。"""
        set_trace_context(TraceContext(action_id="existing", user_id="user-1"))

        with TraceContextManager(goal_handle="G1"):
            ctx = get_trace_context()
            assert ctx is not None
            assert ctx.action_id == "existing"
            assert ctx.user_id == "user-1"
            assert ctx.goal_handle == "G1"

        # クリーンアップ
        set_trace_context(None)

    def test_empty_optional_values_do_not_clear_existing_context(self) -> None:
        """None/空文字の更新で既存トレースIDが消えないことを確認。"""
        set_trace_context(
            TraceContext(
                user_id="user-1",
                request_id="job-1",
                local_job_id="local-job-1",
                suggestion_id="sug-1",
            )
        )

        with TraceContextManager(
            user_id="",
            request_id=None,
            local_job_id=" ",
            suggestion_id=" ",
        ):
            ctx = get_trace_context()
            assert ctx is not None
            assert ctx.user_id == "user-1"
            assert ctx.request_id == "job-1"
            assert ctx.local_job_id == "local-job-1"
            assert ctx.suggestion_id == "sug-1"

        set_trace_context(None)


class TestTraceContextFilter:
    """TraceContextFilter のテスト。"""

    def test_adds_trace_ids_to_log_record(self) -> None:
        """ログレコードにトレース情報が追加されることを確認。"""
        set_trace_context(TraceContext(action_id="test-action", goal_handle="G1"))

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        filter_instance = TraceContextFilter()
        result = filter_instance.filter(record)

        assert result is True
        assert hasattr(record, "action_id")
        assert record.action_id == "test-action"  # type: ignore[attr-defined]
        assert hasattr(record, "goal_handle")
        assert record.goal_handle == "G1"  # type: ignore[attr-defined]
        assert hasattr(record, "trace_ids")
        assert "action_id=test-action" in record.trace_ids  # type: ignore[attr-defined]

        # クリーンアップ
        set_trace_context(None)

    def test_handles_no_context(self) -> None:
        """コンテキストがない場合でもエラーにならないことを確認。"""
        set_trace_context(None)

        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="Test message",
            args=(),
            exc_info=None,
        )

        filter_instance = TraceContextFilter()
        result = filter_instance.filter(record)

        assert result is True
        assert hasattr(record, "trace_ids")
        assert record.trace_ids == ""  # type: ignore[attr-defined]
