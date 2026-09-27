import sqlite3
from collections.abc import Callable

from pantaray_agents.local_runtime.action_conversation.history_queries import (
    ActionHistoryToolRow,
    ActionHistoryUserRow,
    TimelineAnchor,
    UnadoptedAnchor,
    history_anchor_exists,
    read_action_timeline_frontier,
    read_timeline_history,
    read_unadopted_history,
)
from pantaray_agents.local_runtime.action_conversation.sqlite_visibility import (
    register_action_tool_visibility_sqlite,
)


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    register_action_tool_visibility_sqlite(connection)
    connection.executescript(
        """
        CREATE TABLE agent_action_steps(
          step_id TEXT PRIMARY KEY,action_id TEXT,user_id TEXT,step_number INTEGER,
          step_type TEXT,step_name TEXT,status TEXT,accepted_sequence INTEGER,
          user_message_id TEXT,user_message_json TEXT,user_request_text TEXT,
          adopted_process_id TEXT,expected_process_id TEXT,adoption_canceled_at TEXT,
          tool_output TEXT,tool_args TEXT,llm_response_text TEXT);
        CREATE INDEX idx_agent_action_steps_action_timeline
          ON agent_action_steps(action_id,step_number DESC,step_id DESC)
          WHERE step_number IS NOT NULL
            AND step_type IN ('user_request','assistant_message','tool_execution');
        CREATE INDEX idx_agent_action_steps_adopted_process
          ON agent_action_steps(user_id,action_id,adopted_process_id,step_number,step_id)
          WHERE adopted_process_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_agent_action_steps_action_accepted_sequence
          ON agent_action_steps(action_id,accepted_sequence)
          WHERE accepted_sequence IS NOT NULL;
        CREATE INDEX idx_agent_action_steps_adopted_user_timeline
          ON agent_action_steps(
            user_id,action_id,step_number DESC,step_id DESC,adopted_process_id)
          WHERE step_number IS NOT NULL AND step_type='user_request'
            AND status='success' AND adopted_process_id IS NOT NULL;
        CREATE INDEX idx_agent_action_steps_unadopted_user_sequence
          ON agent_action_steps(
            user_id,action_id,accepted_sequence DESC,step_id DESC)
          WHERE step_type='user_request' AND step_number IS NULL
            AND adopted_process_id IS NULL AND accepted_sequence IS NOT NULL;
        """
    )
    rows = (
        ("user-1", 1, "user_request", "user_request", "success", 1, "m1", "run-1"),
        ("tool-a", 2, "tool_execution", "tool::read", "success", None, None, None),
        ("user-2", 3, "user_request", "user_request", "success", 2, "m2", "run-1"),
        ("tool-b", 4, "tool_execution", "tool::bash", "error", None, None, None),
        ("tool-c", 4, "tool_execution", "tool::read", "success", None, None, None),
        ("user-3", 5, "user_request", "user_request", "success", 3, "m3", "run-2"),
        (
            "final",
            99,
            "tool_execution",
            "tool::submit_final_answer",
            "success",
            None,
            None,
            None,
        ),
        ("think", 100, "tool_execution", "tool::thinking", "success", None, None, None),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,
        accepted_sequence,user_message_id,user_message_json,user_request_text,
        adopted_process_id,tool_output)
        VALUES (?,'a','u',?,?,?,?,?,?,'{}','request',?,
                CASE WHEN ?='tool_execution' THEN '{"schema_version":1}' END)""",
        tuple((*row, row[2]) for row in rows),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_type,step_name,status,accepted_sequence,
        user_message_id,user_message_json,user_request_text,expected_process_id,
        adoption_canceled_at) VALUES (?,'a','u','user_request',
        'user_request','success',?,?,'{}','pending','run-2',?)""",
        (("pending-5", 5, "m5", None), ("canceled-4", 4, "m4", "now")),
    )
    return connection


def test_bounded_keysets_filter_before_limit_and_carry_tool_owner() -> None:
    connection = _connection()
    queries: list[str] = []
    connection.set_trace_callback(queries.append)
    # ``limit`` counts runs and a run is returned whole: run-2 is only its
    # USER row (its later tool rows are hidden), run-1 is five rows.
    latest = read_timeline_history(connection, "u", "a", None, 1)
    assert [row.step_id for row in latest.rows] == ["user-3"]
    assert latest.has_more
    older = read_timeline_history(connection, "u", "a", TimelineAnchor(5, "user-3"), 1)
    assert [row.step_id for row in older.rows] == [
        "tool-c",
        "tool-b",
        "user-2",
        "tool-a",
        "user-1",
    ]
    assert not older.has_more
    assert older.rows[1] == ActionHistoryToolRow(
        "tool-b", 4, "bash", "error", '{"schema_version":1}', None, "run-1"
    )
    both = read_timeline_history(connection, "u", "a", None, 2)
    assert [row.step_id for row in both.rows] == [
        "user-3",
        *[r.step_id for r in older.rows],
    ]
    assert not both.has_more
    assert not history_anchor_exists(connection, "u", "a", "timeline", 100, "think")

    unadopted = read_unadopted_history(connection, "u", "a", None, 1)
    assert unadopted.rows[0] == ActionHistoryUserRow(
        "pending-5", None, 5, "m5", "{}", "pending", None, "run-2", None, "user_request"
    )
    assert unadopted.has_more
    older_unadopted = read_unadopted_history(
        connection, "u", "a", UnadoptedAnchor(5, "pending-5"), 1
    )
    assert older_unadopted.rows[0].step_id == "canceled-4"
    assert history_anchor_exists(connection, "u", "a", "unadopted", 5, "pending-5")
    connection.execute("DELETE FROM agent_action_steps WHERE step_id='pending-5'")
    assert not history_anchor_exists(connection, "u", "a", "unadopted", 5, "pending-5")

    for prefix, indexes in (
        (
            "SELECT source.step_type",
            (
                "idx_agent_action_steps_action_timeline",
                "idx_agent_action_steps_adopted_user_timeline",
            ),
        ),
        (
            "SELECT source.step_id",
            ("idx_agent_action_steps_unadopted_user_sequence",),
        ),
    ):
        sql = next(query for query in queries if query.lstrip().startswith(prefix))
        plan = connection.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
        details = tuple(str(row[3]) for row in plan)
        assert all(
            any(f"USING INDEX {index}" in detail for detail in details)
            for index in indexes
        )
        if prefix == "SELECT source.step_type":
            assert not any("USE TEMP B-TREE" in detail for detail in details)


def _with_vm_steps[T](
    connection: sqlite3.Connection, operation: Callable[[], T]
) -> tuple[T, int]:
    count = 0

    def count_vm_step() -> int:
        nonlocal count
        count += 1
        return 0

    connection.set_progress_handler(count_vm_step, 1)
    try:
        result = operation()
    finally:
        connection.set_progress_handler(None, 0)
    return result, count


def _insert_visible_tools(
    connection: sqlite3.Connection, *, first_step: int, count: int
) -> None:
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,tool_output)
        VALUES (?,'a','u',?,'tool_execution','tool::read','success','{}')""",
        (
            (f"scale-tool-{step_number}", step_number)
            for step_number in range(first_step, first_step + count)
        ),
    )


def _insert_adopted_users(
    connection: sqlite3.Connection, *, first_sequence: int, count: int
) -> None:
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,
        accepted_sequence,user_message_id,user_message_json,user_request_text,
        adopted_process_id)
        VALUES (?,'a','u',?,'user_request','user_request','success',?,?,'{}',
                'request',?)""",
        (
            (
                f"scale-user-{sequence}",
                sequence,
                sequence,
                f"scale-message-{sequence}",
                f"scale-run-{sequence}",
            )
            for sequence in range(first_sequence, first_sequence + count)
        ),
    )


def test_tool_owner_lookup_is_independent_of_same_run_tool_count() -> None:
    connection = _connection()
    _insert_visible_tools(connection, first_step=101, count=20)

    baseline_page, baseline_steps = _with_vm_steps(
        connection,
        lambda: read_timeline_history(connection, "u", "a", None, 1),
    )
    _insert_visible_tools(connection, first_step=121, count=2_000)
    grown_page, grown_steps = _with_vm_steps(
        connection,
        lambda: read_timeline_history(connection, "u", "a", None, 1),
    )

    # A page is the whole run, so it grows with the run. What must not grow is
    # the cost of finding each row's owner: per-row work stays flat.
    assert len(baseline_page.rows) == 21
    assert len(grown_page.rows) == 2_021
    assert all(
        row.owning_run_id == "run-2"
        for row in grown_page.rows
        if isinstance(row, ActionHistoryToolRow)
    )
    assert grown_steps / len(grown_page.rows) <= 1.5 * (
        baseline_steps / len(baseline_page.rows)
    )


def test_unadopted_page_is_independent_of_adopted_user_history() -> None:
    connection = _connection()
    connection.execute("DELETE FROM agent_action_steps WHERE step_number IS NULL")

    empty_baseline_page, empty_baseline_steps = _with_vm_steps(
        connection,
        lambda: read_unadopted_history(connection, "u", "a", None, 10),
    )
    _insert_adopted_users(connection, first_sequence=101, count=2_000)
    empty_grown_page, empty_grown_steps = _with_vm_steps(
        connection,
        lambda: read_unadopted_history(connection, "u", "a", None, 10),
    )
    connection.execute(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_type,step_name,status,accepted_sequence,
        user_message_id,user_message_json,user_request_text,expected_process_id)
        VALUES ('only-unadopted','a','u','user_request','user_request','success',
                5000,'only-message','{}','pending','run-pending')"""
    )
    one_baseline_page, one_baseline_steps = _with_vm_steps(
        connection,
        lambda: read_unadopted_history(connection, "u", "a", None, 10),
    )
    _insert_adopted_users(connection, first_sequence=5001, count=2_000)
    one_grown_page, one_grown_steps = _with_vm_steps(
        connection,
        lambda: read_unadopted_history(connection, "u", "a", None, 10),
    )

    assert empty_baseline_page.rows == empty_grown_page.rows == ()
    assert [row.step_id for row in one_baseline_page.rows] == ["only-unadopted"]
    assert one_grown_page == one_baseline_page
    assert empty_grown_steps <= empty_baseline_steps
    assert one_grown_steps <= one_baseline_steps


def test_timeline_keyset_seeks_past_same_step_newer_identities() -> None:
    connection = _connection()
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,tool_output)
        VALUES (?,'a','u',200,'tool_execution','tool::read','success','{}')""",
        ((f"a-page-{index:04d}",) for index in range(10)),
    )
    anchor = TimelineAnchor(200, "m-page-frontier")
    baseline, baseline_steps = _with_vm_steps(
        connection,
        lambda: read_timeline_history(connection, "u", "a", anchor, 5),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,tool_output)
        VALUES (?,'a','u',200,'tool_execution','tool::read','success','{}')""",
        ((f"z-newer-{index:04d}",) for index in range(5_000)),
    )
    grown, grown_steps = _with_vm_steps(
        connection,
        lambda: read_timeline_history(connection, "u", "a", anchor, 5),
    )

    assert grown == baseline
    assert grown_steps <= baseline_steps + 100


def test_durable_timeline_frontier_is_independent_of_hidden_tail_size() -> None:
    connection = _connection()
    queries: list[str] = []
    connection.set_trace_callback(queries.append)
    baseline, baseline_steps = _with_vm_steps(
        connection,
        lambda: read_action_timeline_frontier(connection, "u", "a"),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
        step_id,action_id,user_id,step_number,step_type,step_name,status,tool_output)
        VALUES (?,'a','u',?,'tool_execution','tool::thinking','success','{}')""",
        ((f"hidden-tail-{index:04d}", 101 + index) for index in range(5_000)),
    )
    grown, grown_steps = _with_vm_steps(
        connection,
        lambda: read_action_timeline_frontier(connection, "u", "a"),
    )
    connection.set_trace_callback(None)

    assert baseline == TimelineAnchor(100, "think")
    assert grown == TimelineAnchor(5_100, "hidden-tail-4999")
    assert grown_steps <= baseline_steps + 100
    sql = next(
        query
        for query in queries
        if query.lstrip().startswith("SELECT step_number,step_id")
    )
    assert "pantaray_action_visible_tool" not in sql
    plan = connection.execute(f"EXPLAIN QUERY PLAN {sql}").fetchall()
    assert any(
        "USING INDEX idx_agent_action_steps_action_timeline" in str(row[3])
        for row in plan
    )
