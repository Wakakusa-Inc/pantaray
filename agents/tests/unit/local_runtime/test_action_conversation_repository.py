import sqlite3
from typing import Literal

import pytest

from pantaray_agents.local_runtime.action_conversation.cursor import (
    ActionConversationRunBoundary,
    ActionConversationTimelineCursor,
    decode_action_conversation_cursor,
    encode_action_conversation_cursor,
)
from pantaray_agents.local_runtime.action_conversation.repository import (
    ActionConversationCursorConflictError,
    ActionConversationIntegrityError,
    read_action_conversation_history_page_in_connection,
)
from pantaray_agents.local_runtime.action_conversation.sqlite_visibility import (
    register_action_tool_visibility_sqlite,
)
from pantaray_agents.schema.agent.action_message import (
    ActionUserMessageInput,
    SuggestionApprovalInput,
)
from pantaray_agents.schema.agent.action_message_codec import (
    render_action_user_request_text,
    serialize_action_user_message,
)

HISTORY_ROW_COUNT = 2_000
CURRENT_TIMELINE_CEILING = ActionConversationRunBoundary(
    run_id="run-current", step_number=5, step_id="latest-tool"
)
_ADOPT_PENDING = """UPDATE agent_action_steps
 SET step_number=6, adopted_process_id='run-current'
 WHERE step_id='pending-older' AND step_number IS NULL
   AND adopted_process_id IS NULL AND expected_process_id='run-current'"""
_APPEND_HIDDEN = """INSERT INTO agent_action_steps(
          step_id,action_id,user_id,step_number,step_type,step_name,status,
          accepted_sequence,user_message_id,user_message_json,user_request_text,
          adopted_process_id,expected_process_id,adoption_canceled_at,tool_output,tool_args) VALUES
 ('hidden-tool','action-1','user-1',6,'tool_execution','tool::thinking','success',
  NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{}',NULL)"""


def _conversation_connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    register_action_tool_visibility_sqlite(connection)
    connection.executescript(
        """
        CREATE TABLE agent_actions(
          action_id TEXT PRIMARY KEY,user_id TEXT,suggestion_id TEXT,status TEXT,
          initial_user_message_id TEXT NOT NULL);
        CREATE TABLE agent_action_steps(
          step_id TEXT PRIMARY KEY,action_id TEXT,user_id TEXT,step_number INTEGER,
          step_type TEXT,step_name TEXT,status TEXT,accepted_sequence INTEGER,
          user_message_id TEXT,user_message_json TEXT,user_request_text TEXT,
          adopted_process_id TEXT,expected_process_id TEXT,adoption_canceled_at TEXT,
          tool_output TEXT,tool_args TEXT,llm_response_text TEXT);
        CREATE UNIQUE INDEX uq_agent_action_steps_user_message
          ON agent_action_steps(user_id,user_message_id) WHERE user_message_id IS NOT NULL;
        CREATE INDEX idx_agent_action_steps_action_timeline
          ON agent_action_steps(action_id,step_number DESC,step_id DESC)
          WHERE step_number IS NOT NULL
            AND step_type IN ('user_request','assistant_message','tool_execution');
        CREATE INDEX idx_agent_action_steps_adopted_process
          ON agent_action_steps(
            user_id,action_id,adopted_process_id,step_number ASC,step_id ASC)
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
        INSERT INTO agent_actions VALUES ('action-1','user-1',NULL,'processing','old-message');
        INSERT INTO agent_action_steps(
          step_id,action_id,user_id,step_number,step_type,step_name,status,
          accepted_sequence,user_message_id,user_message_json,user_request_text,
          adopted_process_id,expected_process_id,adoption_canceled_at,tool_output,tool_args) VALUES
          ('old-user','action-1','user-1',1,'user_request','user_request',
           'success',1,'old-message','{}','request','run-old',NULL,NULL,NULL,NULL),
          ('old-tool','action-1','user-1',2,'tool_execution','tool::bash',
           'success',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{}',NULL),
          ('a-current-tool','action-1','user-1',4,'tool_execution','tool::read',
           'success',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{}',
           '{"tool_id":"read","args":{"path":"src/app.py"}}'),
          ('z-current-user','action-1','user-1',3,'user_request','user_request',
           'success',2,'current-message','{}','request','run-current',NULL,NULL,NULL,NULL),
          ('latest-tool','action-1','user-1',5,'tool_execution','tool::apply_patch',
           'success',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'{}',NULL),
          ('pending','action-1','user-1',NULL,'user_request','user_request',
           'success',5,'pending-message','{}','pending',NULL,'run-current',NULL,NULL,NULL),
          ('canceled','action-1','user-1',NULL,'user_request','user_request',
           'success',4,'canceled-message','{}','pending',NULL,'run-current','now',NULL,NULL);
        """
    )
    connection.commit()
    return connection


@pytest.mark.parametrize("corruption", ["wrong_suggestion", "missing_owner"])
def test_initial_approval_is_read_independently_of_paged_runs(corruption: str) -> None:
    connection = _conversation_connection()
    message = ActionUserMessageInput(
        message_id="old-message",
        content="Review the changes?",
        images=(),
        suggestion_approval=SuggestionApprovalInput(
            suggestion_id="suggestion-1",
            approved_at="2026-08-30T00:00:00Z",
            summary="Private provenance",
        ),
    )
    connection.execute("UPDATE agent_actions SET suggestion_id='suggestion-1'")
    connection.execute(
        "UPDATE agent_action_steps SET user_message_json=?,user_request_text=? WHERE step_id='old-user'",
        (
            serialize_action_user_message(message),
            render_action_user_request_text(message),
        ),
    )
    page = read_action_conversation_history_page_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        cursor=None,
        limit=1,
    )
    assert "old-user" not in [row.step_id for row in page.rows]
    assert page.action.model_dump(mode="json")["approved_suggestion"] == {
        "suggestion_id": "suggestion-1",
        "content": "Review the changes?",
    }
    connection.execute(
        "UPDATE agent_actions SET suggestion_id='another-suggestion'"
        if corruption == "wrong_suggestion"
        else "UPDATE agent_action_steps SET user_id='another-user' WHERE step_id='old-user'"
    )
    with pytest.raises(ActionConversationIntegrityError):
        read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=None,
            limit=1,
        )
    connection.close()


@pytest.mark.parametrize("with_assistant", [False, True])
def test_repository_pages_each_scope_without_duplicate_or_omitted_identity(
    with_assistant: bool,
) -> None:
    connection = _conversation_connection()
    if with_assistant:
        # Leave one earlier position for each run's initial assistant message.
        connection.execute("UPDATE agent_action_steps SET step_number=step_number*2")
        connection.executemany(
            """INSERT INTO agent_action_steps(
                step_id,action_id,user_id,step_number,step_type,step_name,status,
                adopted_process_id,llm_response_text)
            VALUES (?,'action-1','user-1',?,'assistant_message','assistant_message',
                    'success',?,'Earlier assistant message')""",
            (
                ("a-old-assistant", 1, "run-old"),
                ("a-current-assistant", 5, "run-current"),
            ),
        )
        connection.commit()
    with pytest.raises(ValueError, match="caller-owned transaction"):
        read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=None,
            limit=2,
        )

    queries: list[str] = []
    connection.set_trace_callback(queries.append)
    connection.execute("BEGIN")
    pages = []
    cursor = None
    while True:
        page = read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=cursor,
            limit=2,
        )
        pages.append(page)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    # A page is whole runs: the current run never splits, however many tool
    # rows it has, so its USER row can never fall behind "load earlier".
    assert [page.scope for page in pages] == [
        "current_timeline",
        "unadopted",
        "older_timeline",
    ]
    assert [[row.step_id for row in page.rows] for page in pages] == [
        ["latest-tool", "a-current-tool", "z-current-user"]
        + (["a-current-assistant"] if with_assistant else []),
        ["pending", "canceled"],
        ["old-tool", "old-user"] + (["a-old-assistant"] if with_assistant else []),
    ]
    assert all(" OFFSET " not in f" {query.upper()} " for query in queries)

    for payload in (
        ActionConversationTimelineCursor(
            user_id="other-user",
            action_id="action-1",
            scope="current_timeline",
            step_number=5,
            step_id="latest-tool",
            timeline_ceiling=CURRENT_TIMELINE_CEILING,
        ),
        ActionConversationTimelineCursor(
            user_id="user-1",
            action_id="action-1",
            scope="current_timeline",
            step_number=5,
            step_id="missing",
            timeline_ceiling=CURRENT_TIMELINE_CEILING,
        ),
        ActionConversationTimelineCursor(
            user_id="user-1",
            action_id="action-1",
            scope="current_timeline",
            step_number=2,
            step_id="old-tool",
            timeline_ceiling=CURRENT_TIMELINE_CEILING,
        ),
    ):
        with pytest.raises(ActionConversationCursorConflictError):
            read_action_conversation_history_page_in_connection(
                connection=connection,
                user_id="user-1",
                action_id="action-1",
                cursor=encode_action_conversation_cursor(payload),
                limit=2,
            )

    decoded = decode_action_conversation_cursor(pages[1].next_cursor or "")
    assert decoded.scope == "unadopted"
    assert decoded.timeline_boundary is not None


@pytest.mark.parametrize(
    ("scope", "mutation"),
    [
        pytest.param("current_timeline", _ADOPT_PENDING, id="current-adoption"),
        pytest.param("current_timeline", _APPEND_HIDDEN, id="current-tool"),
        pytest.param("unadopted", _ADOPT_PENDING, id="unadopted-adoption"),
    ],
)
def test_active_scope_cursor_conflicts_when_durable_frontier_changes(
    scope: Literal["current_timeline", "unadopted"],
    mutation: str,
) -> None:
    connection = _conversation_connection()
    connection.execute("BEGIN")
    connection.execute(
        """INSERT INTO agent_action_steps(
          step_id,action_id,user_id,step_number,step_type,step_name,status,
          accepted_sequence,user_message_id,user_message_json,user_request_text,
          adopted_process_id,expected_process_id,adoption_canceled_at,tool_output,tool_args) VALUES
          ('pending-older','action-1','user-1',NULL,'user_request','user_request',
           'success',3,'pending-older-message','{}','pending',NULL,
           'run-current',NULL,NULL,NULL)"""
    )
    current = read_action_conversation_history_page_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        cursor=None,
        limit=2 if scope == "current_timeline" else 10,
    )
    assert current.next_cursor is not None
    if scope == "unadopted":
        page = read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=current.next_cursor,
            limit=1,
        )
    else:
        page = current
    assert page.next_cursor is not None

    connection.execute(mutation)

    with pytest.raises(
        ActionConversationCursorConflictError,
        match="timeline changed after pagination started",
    ):
        read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=page.next_cursor,
            limit=2,
        )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        pytest.param(
            """INSERT INTO agent_action_steps(
          step_id,action_id,user_id,step_number,step_type,step_name,status,
          accepted_sequence,user_message_id,user_message_json,user_request_text,
          adopted_process_id,expected_process_id,adoption_canceled_at,tool_output,tool_args) VALUES
              ('pending-new','action-1','user-1',NULL,'user_request','user_request',
               'success',6,'pending-new-message','{}','pending',NULL,
               'run-current',NULL,NULL,NULL)""",
            "unadopted scope changed after pagination started",
            id="newer-pending-user",
        ),
        pytest.param(
            """INSERT INTO agent_action_steps(
          step_id,action_id,user_id,step_number,step_type,step_name,status,
          accepted_sequence,user_message_id,user_message_json,user_request_text,
          adopted_process_id,expected_process_id,adoption_canceled_at,tool_output,tool_args) VALUES
              ('new-user','action-1','user-1',6,'user_request','user_request',
               'success',6,'new-message','{}','request','run-new',NULL,NULL,NULL,
               NULL)""",
            "run boundary changed after scope transition",
            id="latest-run-boundary",
        ),
    ],
)
def test_unadopted_cursor_conflicts_when_scope_authority_changes(
    mutation: str,
    message: str,
) -> None:
    connection = _conversation_connection()
    connection.execute("BEGIN")
    current = read_action_conversation_history_page_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        cursor=None,
        limit=10,
    )
    unadopted = read_action_conversation_history_page_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        cursor=current.next_cursor,
        limit=1,
    )
    assert unadopted.next_cursor is not None
    connection.execute(mutation)

    with pytest.raises(ActionConversationCursorConflictError, match=message):
        read_action_conversation_history_page_in_connection(
            connection=connection,
            user_id="user-1",
            action_id="action-1",
            cursor=unadopted.next_cursor,
            limit=1,
        )


def test_latest_run_boundary_queries_are_independent_of_action_history() -> None:
    connection = _conversation_connection()
    traced: list[str] = []
    connection.set_trace_callback(traced.append)
    connection.execute("BEGIN")
    read_action_conversation_history_page_in_connection(
        connection=connection,
        user_id="user-1",
        action_id="action-1",
        cursor=None,
        limit=2,
    )
    connection.set_trace_callback(None)
    boundary_queries = tuple(
        query
        for query in traced
        if "WITH latest AS" in query or "WITH boundary AS" in query
    )
    assert len(boundary_queries) == 1
    plans = tuple(
        connection.execute(f"EXPLAIN QUERY PLAN {query}").fetchall()
        for query in boundary_queries
    )

    def run_boundary_query(query: str) -> tuple[tuple[object, ...], int]:
        vm_steps = 0

        def count_vm_step() -> int:
            nonlocal vm_steps
            vm_steps += 1
            return 0

        connection.set_progress_handler(count_vm_step, 1)
        try:
            rows = tuple(connection.execute(query).fetchall())
        finally:
            connection.set_progress_handler(None, 0)
        return rows, vm_steps

    baseline = tuple(run_boundary_query(query) for query in boundary_queries)
    connection.executemany(
        """INSERT INTO agent_action_steps(
               step_id,action_id,user_id,step_number,step_type,step_name,status,
               tool_output)
           VALUES (?,'action-1','user-1',2,'tool_execution','tool::bash',
                   'success','{}')""",
        ((f"older-tool-{index}",) for index in range(HISTORY_ROW_COUNT)),
    )
    connection.executemany(
        """INSERT INTO agent_action_steps(
               step_id,action_id,user_id,step_number,step_type,step_name,status,
               tool_output)
           VALUES (?,'action-1','user-1',?,'tool_execution','tool::bash',
                   'success','{}')""",
        ((f"current-tool-{index}", index + 6) for index in range(HISTORY_ROW_COUNT)),
    )
    after_tool_growth = tuple(run_boundary_query(query) for query in boundary_queries)
    connection.executemany(
        """INSERT INTO agent_action_steps(
               step_id,action_id,user_id,step_type,step_name,status,
               accepted_sequence,user_message_id,user_message_json,
               user_request_text,expected_process_id)
           VALUES (?,'action-1','user-1','user_request','user_request','success',
                   ?,?,'{}','pending','run-current')""",
        (
            (f"unadopted-{index}", index + 100, f"unadopted-message-{index}")
            for index in range(HISTORY_ROW_COUNT)
        ),
    )
    after_unadopted_growth = tuple(
        run_boundary_query(query) for query in boundary_queries
    )

    plan_details = tuple(str(row[3]) for plan in plans for row in plan)
    assert any(
        "USING INDEX idx_agent_action_steps_adopted_user_timeline" in detail
        for detail in plan_details
    )
    assert any(
        "USING COVERING INDEX idx_agent_action_steps_adopted_process" in detail
        for detail in plan_details
    )
    assert all("TEMP B-TREE" not in detail for detail in plan_details)
    baseline_results = tuple(result for result, _ in baseline)
    for grown in (after_tool_growth, after_unadopted_growth):
        assert tuple(result for result, _ in grown) == baseline_results
        assert all(
            grown_steps <= baseline_steps
            for (_, grown_steps), (_, baseline_steps) in zip(
                grown, baseline, strict=True
            )
        )
