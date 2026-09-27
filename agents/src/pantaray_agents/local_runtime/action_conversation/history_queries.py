"""Bounded SQLite identity reads for Action conversation history."""

import sqlite3
from dataclasses import dataclass
from typing import Literal, NamedTuple, cast

from pantaray_agents.local_runtime.action_conversation.sqlite_visibility import (
    ACTION_TOOL_VISIBILITY_SQL_FUNCTION,
)
from pantaray_agents.schema.action_conversation import ActionStepStatus


class TimelineAnchor(NamedTuple):
    step_number: int
    step_id: str


class UnadoptedAnchor(NamedTuple):
    accepted_sequence: int
    step_id: str


@dataclass(frozen=True, slots=True)
class ActionHistoryUserRow:
    step_id: str
    step_number: int | None
    accepted_sequence: int
    user_message_id: str | None
    user_message_json: str | None
    user_request_text: str
    adopted_process_id: str | None
    expected_process_id: str | None
    adoption_canceled_at: str | None
    # Which origin wrote the row. The projection is the only reader: a resume
    # turn opens its run like any other but has no message to show.
    step_name: str


@dataclass(frozen=True, slots=True)
class ActionHistoryToolRow:
    step_id: str
    step_number: int
    tool_id: str
    status: ActionStepStatus
    tool_output: str | None
    tool_args: str | None
    owning_run_id: str


@dataclass(frozen=True, slots=True)
class ActionHistoryAssistantRow:
    step_id: str
    step_number: int
    content: str
    owning_run_id: str


type TimelineHistoryRow = (
    ActionHistoryUserRow | ActionHistoryAssistantRow | ActionHistoryToolRow
)


class HistoryQueryPage[T](NamedTuple):
    rows: tuple[T, ...]
    has_more: bool


_OWNER = """
SELECT owner.step_id FROM agent_action_steps AS owner
  INDEXED BY idx_agent_action_steps_adopted_user_timeline
WHERE source.step_type='tool_execution' AND owner.user_id=source.user_id AND owner.action_id=source.action_id
  AND owner.step_number IS NOT NULL AND owner.step_type='user_request'
  AND owner.status='success' AND owner.adopted_process_id IS NOT NULL
  AND owner.step_number<=source.step_number
ORDER BY owner.step_number DESC,owner.step_id DESC LIMIT 1
"""
_TIMELINE_FROM = f"""
FROM agent_action_steps AS source
LEFT JOIN agent_action_steps AS owner ON owner.step_id=({_OWNER})
WHERE source.user_id=:user_id AND source.action_id=:action_id AND source.step_number IS NOT NULL
  AND source.step_type IN ('user_request','assistant_message','tool_execution')
  AND ((source.step_type IN ('user_request','assistant_message') AND source.status='success' AND source.adopted_process_id IS NOT NULL)
    OR (source.step_type='tool_execution' AND {ACTION_TOOL_VISIBILITY_SQL_FUNCTION}(source.step_name) IS NOT NULL
        AND owner.step_id IS NOT NULL))
"""
_TIMELINE_SELECT = f"""
SELECT source.step_type,source.step_id,source.step_number,source.accepted_sequence,
 source.user_message_id,source.user_message_json,source.user_request_text,source.adopted_process_id,source.expected_process_id,source.adoption_canceled_at,source.step_name,
 {ACTION_TOOL_VISIBILITY_SQL_FUNCTION}(source.step_name),
 source.status,source.tool_output,source.tool_args,owner.adopted_process_id,
 source.llm_response_text {_TIMELINE_FROM}
"""
_UNADOPTED_FROM = """
FROM agent_action_steps AS source
  INDEXED BY idx_agent_action_steps_unadopted_user_sequence
WHERE source.user_id=:user_id AND source.action_id=:action_id AND source.step_type='user_request'
 AND source.step_number IS NULL AND source.adopted_process_id IS NULL AND source.accepted_sequence IS NOT NULL
"""
_UNADOPTED_SELECT = f"""
SELECT source.step_id,source.step_number,source.accepted_sequence,source.user_message_id,source.user_message_json,source.user_request_text,source.adopted_process_id,source.expected_process_id,source.adoption_canceled_at,source.step_name {_UNADOPTED_FROM}
"""


def read_timeline_history(
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    before: TimelineAnchor | None,
    limit: int,
) -> HistoryQueryPage[TimelineHistoryRow]:
    """Read up to ``limit`` logical runs, newest first, each run whole.

    A page never splits a run: it holds every visible row from the newest run
    down to the first message of the ``limit``-th run. Cutting by row count
    dropped a run's own USER row behind "load earlier messages" as soon as its
    tool rows outnumbered the page, so the conversation folded at the agent's
    pace. ``has_more`` says an older run exists past the page's oldest root.
    """
    params: dict[str, str | int] = {"user_id": user_id, "action_id": action_id}
    keyset = ""
    if before is not None:
        keyset = """AND (source.step_number,source.step_id)
 < (:before_number,:before_id)"""
        params.update(before_number=before.step_number, before_id=before.step_id)
    # A run's USER rows are contiguous in timeline order: runs never interleave,
    # and a steer adopted mid-run belongs to that run. Walking the USER rows
    # newest-first therefore meets each run once.
    user_rows = connection.execute(
        f"""SELECT source.adopted_process_id
        FROM agent_action_steps AS source
          INDEXED BY idx_agent_action_steps_adopted_user_timeline
        WHERE source.user_id=:user_id AND source.action_id=:action_id
          AND source.step_number IS NOT NULL AND source.step_type='user_request'
          AND source.status='success' AND source.adopted_process_id IS NOT NULL {keyset}
        ORDER BY source.step_number DESC,source.step_id DESC""",
        params,
    ).fetchall()
    current_run: str | None = None
    runs = 0
    has_more = False
    for (run_id,) in user_rows:
        if run_id != current_run:
            if runs == limit:
                has_more = True
                break
            runs += 1
            current_run = run_id
    if current_run is None:
        return HistoryQueryPage((), False)
    # An assistant message may precede the root USER that opens this run.
    first_message = connection.execute(
        """SELECT step_number,step_id FROM agent_action_steps
        WHERE user_id=? AND action_id=? AND adopted_process_id=?
          AND step_number IS NOT NULL
        ORDER BY step_number ASC,step_id ASC LIMIT 1""",
        (user_id, action_id, current_run),
    ).fetchone()
    floor = TimelineAnchor(cast("int", first_message[0]), cast("str", first_message[1]))
    params.update(floor_number=floor.step_number, floor_id=floor.step_id)
    records = connection.execute(
        f"""{_TIMELINE_SELECT} {keyset}
        AND (source.step_number,source.step_id) >= (:floor_number,:floor_id)
        ORDER BY source.step_number DESC,source.step_id DESC""",
        params,
    ).fetchall()
    return HistoryQueryPage(tuple(_timeline_row(row) for row in records), has_more)


def read_action_timeline_frontier(
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
) -> TimelineAnchor | None:
    """Read the latest durable conversation position from a caller-owned connection."""

    row = connection.execute(
        """
        SELECT step_number,step_id
        FROM agent_action_steps
          INDEXED BY idx_agent_action_steps_action_timeline
        WHERE action_id=? AND user_id=? AND step_number>0
          AND step_type IN ('user_request','assistant_message','tool_execution')
        ORDER BY step_number DESC,step_id DESC LIMIT 1
        """,
        (action_id, user_id),
    ).fetchone()
    if row is None:
        return None
    return TimelineAnchor(cast("int", row[0]), cast("str", row[1]))


def history_anchor_exists(
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    scope: Literal["timeline", "unadopted"],
    position: int,
    step_id: str,
) -> bool:
    if scope == "timeline":
        from_sql, position_column = _TIMELINE_FROM, "step_number"
    else:
        from_sql, position_column = _UNADOPTED_FROM, "accepted_sequence"
    record = connection.execute(
        f"""SELECT 1 {from_sql} AND source.{position_column}=:position
        AND source.step_id=:step_id LIMIT 1""",
        {
            "user_id": user_id,
            "action_id": action_id,
            "position": position,
            "step_id": step_id,
        },
    ).fetchone()
    return record is not None


def read_unadopted_history(
    connection: sqlite3.Connection,
    user_id: str,
    action_id: str,
    before: UnadoptedAnchor | None,
    limit: int,
) -> HistoryQueryPage[ActionHistoryUserRow]:
    keyset = ""
    params: dict[str, str | int] = {
        "user_id": user_id,
        "action_id": action_id,
        "fetch_limit": limit + 1,
    }
    if before is not None:
        keyset = """AND (source.accepted_sequence,source.step_id)
 < (:before_sequence,:before_id)"""
        params["before_sequence"] = before.accepted_sequence
        params["before_id"] = before.step_id
    records = connection.execute(
        f"""{_UNADOPTED_SELECT} {keyset}
        ORDER BY source.accepted_sequence DESC,source.step_id DESC LIMIT :fetch_limit""",
        params,
    ).fetchall()
    return HistoryQueryPage(
        tuple(_user_row(row) for row in records[:limit]), len(records) > limit
    )


def _timeline_row(row: sqlite3.Row | tuple[object, ...]) -> TimelineHistoryRow:
    values = tuple(row)
    if values[0] == "user_request":
        return _user_row(values[1:11])
    if values[0] == "assistant_message":
        return ActionHistoryAssistantRow(
            cast("str", values[1]),
            cast("int", values[2]),
            cast("str", values[16]),
            cast("str", values[7]),
        )
    return ActionHistoryToolRow(
        cast("str", values[1]),
        cast("int", values[2]),
        cast("str", values[11]),
        cast("ActionStepStatus", values[12]),
        cast("str | None", values[13]),
        cast("str | None", values[14]),
        cast("str", values[15]),
    )


def _user_row(row: sqlite3.Row | tuple[object, ...]) -> ActionHistoryUserRow:
    values = tuple(row)
    return ActionHistoryUserRow(
        cast("str", values[0]),
        cast("int | None", values[1]),
        cast("int", values[2]),
        cast("str | None", values[3]),
        cast("str | None", values[4]),
        cast("str", values[5]),
        cast("str | None", values[6]),
        cast("str | None", values[7]),
        cast("str | None", values[8]),
        cast("str", values[9]),
    )
