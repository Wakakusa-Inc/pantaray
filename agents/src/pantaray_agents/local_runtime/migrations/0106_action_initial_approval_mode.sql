-- Preserve the original creation request independently of later consent changes.
ALTER TABLE agent_actions ADD COLUMN initial_approval_mode TEXT
    CHECK (initial_approval_mode IN ('prompt_each_time', 'always_allow'));
