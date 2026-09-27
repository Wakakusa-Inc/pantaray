CREATE TABLE action_subagent_resource_claims (
    claim_id TEXT PRIMARY KEY CHECK (LENGTH(TRIM(claim_id)) > 0),
    user_id TEXT NOT NULL,
    action_id TEXT NOT NULL,
    parent_process_id TEXT NOT NULL,
    child_process_id TEXT NOT NULL,
    resource_kind TEXT NOT NULL CHECK (
        resource_kind IN ('workspace_path', 'external_resource')
    ),
    root_identity TEXT NOT NULL CHECK (LENGTH(TRIM(root_identity)) > 0),
    normalized_key TEXT NOT NULL CHECK (LENGTH(TRIM(normalized_key)) > 0),
    acquired_at TEXT NOT NULL CHECK (LENGTH(TRIM(acquired_at)) > 0),
    released_at TEXT CHECK (
        released_at IS NULL OR LENGTH(TRIM(released_at)) > 0
    ),
    FOREIGN KEY (user_id, action_id)
        REFERENCES agent_actions(user_id, action_id) ON DELETE CASCADE,
    FOREIGN KEY (user_id, action_id, parent_process_id)
        REFERENCES processes(user_id, action_id, process_id) ON DELETE NO ACTION,
    FOREIGN KEY (user_id, action_id, child_process_id)
        REFERENCES processes(user_id, action_id, process_id) ON DELETE NO ACTION
);

CREATE INDEX idx_action_subagent_claims_child
ON action_subagent_resource_claims(child_process_id);

CREATE INDEX idx_action_subagent_claims_parent
ON action_subagent_resource_claims(user_id, action_id, parent_process_id);

CREATE INDEX idx_action_subagent_claims_parent_active
ON action_subagent_resource_claims(
    user_id, action_id, parent_process_id,
    resource_kind, root_identity, normalized_key
)
WHERE released_at IS NULL;

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

CREATE TRIGGER trg_action_subagent_claim_limit_insert
BEFORE INSERT ON action_subagent_resource_claims
WHEN (
    SELECT COUNT(*)
    FROM action_subagent_resource_claims
    WHERE child_process_id = NEW.child_process_id
) >= 64
BEGIN
    SELECT RAISE(ABORT, 'Action subagent resource claim limit exceeded');
END;

CREATE TRIGGER trg_action_subagent_claim_identity_immutable
BEFORE UPDATE ON action_subagent_resource_claims
WHEN NEW.claim_id IS NOT OLD.claim_id
  OR NEW.user_id IS NOT OLD.user_id
  OR NEW.action_id IS NOT OLD.action_id
  OR NEW.parent_process_id IS NOT OLD.parent_process_id
  OR NEW.child_process_id IS NOT OLD.child_process_id
  OR NEW.resource_kind IS NOT OLD.resource_kind
  OR NEW.root_identity IS NOT OLD.root_identity
  OR NEW.normalized_key IS NOT OLD.normalized_key
  OR NEW.acquired_at IS NOT OLD.acquired_at
BEGIN
    SELECT RAISE(ABORT, 'Action subagent resource claim identity is immutable');
END;

CREATE TRIGGER trg_action_subagent_claim_release_insert
BEFORE INSERT ON action_subagent_resource_claims
WHEN NEW.released_at IS NOT NULL
BEGIN
    SELECT RAISE(ABORT, 'Action subagent resource claim must be acquired active');
END;

CREATE TRIGGER trg_action_subagent_claim_release_one_way
BEFORE UPDATE OF released_at ON action_subagent_resource_claims
WHEN OLD.released_at IS NOT NULL
  AND NEW.released_at IS NOT OLD.released_at
BEGIN
    SELECT RAISE(ABORT, 'Action subagent resource claim release is immutable');
END;
