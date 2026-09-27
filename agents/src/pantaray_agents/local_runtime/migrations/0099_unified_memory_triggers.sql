PRAGMA foreign_keys = OFF;

CREATE TABLE memory_agent_triggers_v0099 (
    user_id TEXT NOT NULL,
    trigger_kind TEXT NOT NULL CHECK (trigger_kind IN (
        'insight_update_from_insight',
        'fact_from_24h_summary',
        'memory_from_short_insight',
        'memory_from_24h_summary',
        'memory_from_action_terminal'
    )),
    source_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN (
        'pending', 'dispatched', 'skipped', 'blocked'
    )),
    dispatched_job_id TEXT,
    outcome_code TEXT,
    created_at TEXT NOT NULL,
    handled_at TEXT,
    action_id TEXT,
    action_completed_at TEXT,
    source_action_revision_id TEXT,
    turn_start_step_number INTEGER,
    turn_end_step_number INTEGER,
    action_prompt_name TEXT,
    action_prompt_version TEXT,
    suggestion_id TEXT,
    PRIMARY KEY (user_id, trigger_kind, source_id),
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (dispatched_job_id) REFERENCES jobs(job_id),
    CHECK (
        (status = 'pending'
            AND dispatched_job_id IS NULL
            AND outcome_code IS NULL
            AND handled_at IS NULL)
        OR
        (status = 'dispatched'
            AND dispatched_job_id IS NOT NULL
            AND outcome_code = 'JOB_ENQUEUED'
            AND handled_at IS NOT NULL)
        OR
        (status IN ('skipped', 'blocked')
            AND dispatched_job_id IS NULL
            AND outcome_code IS NOT NULL
            AND handled_at IS NOT NULL)
    ),
    CHECK (
        CASE WHEN trigger_kind = 'memory_from_action_terminal' THEN
            action_id IS NOT NULL
            AND action_completed_at IS NOT NULL
            AND turn_start_step_number IS NOT NULL
            AND turn_end_step_number IS NOT NULL
            AND turn_start_step_number >= 1
            AND turn_end_step_number >= turn_start_step_number
            AND action_prompt_name IS NOT NULL
            AND action_prompt_version IS NOT NULL
        ELSE
            action_id IS NULL
            AND action_completed_at IS NULL
            AND source_action_revision_id IS NULL
            AND turn_start_step_number IS NULL
            AND turn_end_step_number IS NULL
            AND action_prompt_name IS NULL
            AND action_prompt_version IS NULL
            AND suggestion_id IS NULL
        END
    )
);

INSERT INTO memory_agent_triggers_v0099(
    user_id, trigger_kind, source_id, status, dispatched_job_id,
    outcome_code, created_at, handled_at
)
SELECT
    user_id, trigger_kind, source_id, status, dispatched_job_id,
    outcome_code, created_at, handled_at
FROM memory_agent_triggers;

DROP TABLE memory_agent_triggers;
ALTER TABLE memory_agent_triggers_v0099 RENAME TO memory_agent_triggers;

CREATE INDEX idx_memory_agent_triggers_pending
ON memory_agent_triggers(user_id, status, created_at, source_id);

CREATE TABLE processes_v0099 (
    process_id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (
        kind IN (
            'suggestion', 'suggestion_critic', 'action', 'action_subagent',
            'insight', 'fact', 'activity_description', 'activity_summary',
            'post_action_pipeline', 'agent_experience', 'memory'
        )
    ),
    status TEXT NOT NULL CHECK (
        status IN (
            'enqueued', 'running', 'paused', 'completed', 'failed',
            'canceled', 'success', 'error', 'abandoned'
        )
    ),
    suggestion_id TEXT,
    action_id TEXT,
    started_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    completed_at TEXT,
    heartbeat_at TEXT NOT NULL,
    terminal_event_id TEXT,
    acknowledged_at TEXT,
    current_job_id TEXT,
    next_event_seq INTEGER NOT NULL CHECK (next_event_seq >= 1),
    parent_process_id TEXT,
    result_collected_at TEXT,
    FOREIGN KEY (user_id) REFERENCES users(user_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, action_id, parent_process_id)
        REFERENCES processes_v0099(user_id, action_id, process_id)
        ON DELETE NO ACTION,
    CHECK (
        (kind = 'action_subagent' AND action_id IS NOT NULL
            AND parent_process_id IS NOT NULL)
        OR
        (kind <> 'action_subagent' AND parent_process_id IS NULL
            AND result_collected_at IS NULL)
    ),
    CHECK (
        result_collected_at IS NULL
        OR status NOT IN ('enqueued', 'running', 'paused')
    )
);

INSERT INTO processes_v0099(
    process_id, user_id, kind, status, suggestion_id, action_id, started_at,
    updated_at, completed_at, heartbeat_at, terminal_event_id,
    acknowledged_at, current_job_id, next_event_seq,
    parent_process_id, result_collected_at
)
SELECT
    process_id, user_id, kind, status, suggestion_id, action_id, started_at,
    updated_at, completed_at, heartbeat_at, terminal_event_id,
    acknowledged_at, current_job_id, next_event_seq,
    parent_process_id, result_collected_at
FROM processes;

DROP TRIGGER trg_action_user_process_identity_insert;
DROP TRIGGER trg_action_user_process_identity_update;
DROP TRIGGER trg_action_user_referenced_process_kind;
DROP TRIGGER trg_action_subagent_parent_insert;
DROP TRIGGER trg_action_subagent_active_limit_insert;
DROP TRIGGER trg_action_subagent_active_limit_update;
DROP TRIGGER trg_action_subagent_identity_immutable;
DROP TRIGGER trg_action_subagent_parent_kind_immutable;
DROP TRIGGER trg_action_subagent_claim_lineage_insert;
DROP TABLE processes;
ALTER TABLE processes_v0099 RENAME TO processes;

CREATE INDEX idx_processes_user_updated
    ON processes(user_id, updated_at DESC);
CREATE INDEX idx_processes_kind_status
    ON processes(kind, status);
CREATE UNIQUE INDEX idx_processes_terminal_event_id
    ON processes(terminal_event_id) WHERE terminal_event_id IS NOT NULL;
CREATE UNIQUE INDEX uq_processes_user_action_process
    ON processes(user_id, action_id, process_id);
CREATE UNIQUE INDEX uq_processes_active_action
    ON processes(action_id)
    WHERE kind = 'action' AND action_id IS NOT NULL
      AND status IN ('enqueued', 'running', 'paused');

CREATE TRIGGER trg_action_subagent_parent_insert
BEFORE INSERT ON processes
WHEN NEW.kind = 'action_subagent' AND NOT EXISTS (
    SELECT 1 FROM processes AS parent
    WHERE parent.process_id = NEW.parent_process_id
      AND parent.user_id = NEW.user_id
      AND parent.action_id = NEW.action_id
      AND parent.kind = 'action'
      AND parent.status IN ('enqueued', 'running', 'paused')
)
BEGIN
    SELECT RAISE(ABORT, 'Action subagent parent is invalid or inactive');
END;

CREATE TRIGGER trg_action_subagent_active_limit_insert
BEFORE INSERT ON processes
WHEN NEW.kind = 'action_subagent'
  AND NEW.status IN ('enqueued', 'running', 'paused')
  AND (
      SELECT COUNT(*) FROM processes
      WHERE kind = 'action_subagent'
        AND parent_process_id = NEW.parent_process_id
        AND status IN ('enqueued', 'running', 'paused')
  ) >= 4
BEGIN
    SELECT RAISE(ABORT, 'Action subagent active child limit exceeded');
END;
CREATE TRIGGER trg_action_subagent_active_limit_update
BEFORE UPDATE OF kind, status, parent_process_id ON processes
WHEN NEW.kind = 'action_subagent'
  AND NEW.status IN ('enqueued', 'running', 'paused')
  AND (
      SELECT COUNT(*) FROM processes
      WHERE kind = 'action_subagent'
        AND parent_process_id = NEW.parent_process_id
        AND process_id <> OLD.process_id
        AND status IN ('enqueued', 'running', 'paused')
  ) >= 4
BEGIN
    SELECT RAISE(ABORT, 'Action subagent active child limit exceeded');
END;

CREATE TRIGGER trg_action_subagent_identity_immutable
BEFORE UPDATE OF kind, user_id, action_id, parent_process_id ON processes
WHEN (OLD.kind = 'action_subagent' OR NEW.kind = 'action_subagent')
  AND (
      NEW.kind IS NOT OLD.kind
      OR NEW.user_id IS NOT OLD.user_id
      OR NEW.action_id IS NOT OLD.action_id
      OR NEW.parent_process_id IS NOT OLD.parent_process_id
  )
BEGIN
    SELECT RAISE(ABORT, 'Action subagent identity is immutable');
END;

CREATE TRIGGER trg_action_subagent_parent_kind_immutable
BEFORE UPDATE OF kind ON processes
WHEN OLD.kind = 'action' AND NEW.kind <> 'action' AND EXISTS (
    SELECT 1 FROM processes AS child
    WHERE child.parent_process_id = OLD.process_id
      AND child.kind = 'action_subagent'
)
BEGIN
    SELECT RAISE(ABORT, 'Action subagent parent kind is immutable');
END;

CREATE TRIGGER trg_action_subagent_claim_lineage_insert
BEFORE INSERT ON action_subagent_resource_claims
WHEN NOT EXISTS (
    SELECT 1
    FROM processes AS child
    JOIN processes AS parent
      ON parent.process_id = child.parent_process_id
     AND parent.user_id = child.user_id
     AND parent.action_id = child.action_id
    WHERE child.process_id = NEW.child_process_id
      AND child.user_id = NEW.user_id
      AND child.action_id = NEW.action_id
      AND child.kind = 'action_subagent'
      AND child.parent_process_id = NEW.parent_process_id
      AND parent.kind = 'action'
)
BEGIN
    SELECT RAISE(ABORT, 'Action subagent resource claim lineage is invalid');
END;

PRAGMA foreign_keys = ON;
