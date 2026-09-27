-- A turn can only be replayed as structured items when the durable record keeps
-- the call identity the model issued: a `function_call` and its
-- `function_call_output` are paired by `call_id`, and the calls a single THINK
-- declared are grouped by the step that declared them.
--
-- `llm_step_id` is that THINK row's `step_id`, carried on the call itself.
-- `parent_step_id` cannot stand in for it: that one is re-derived from the
-- in-memory history when the row is written, as the newest THINK of the row's
-- own phase, so it is NULL for a sibling that runs after the phase advanced and
-- it is nullable again on delete. No foreign key here for that last reason --
-- a step row is only ever deleted with its whole action, and an
-- ON DELETE SET NULL would break the paired-presence check below.
ALTER TABLE agent_action_steps ADD COLUMN call_id TEXT CHECK (
    call_id IS NULL
    OR (step_type = 'tool_execution' AND LENGTH(TRIM(call_id)) > 0)
);

ALTER TABLE agent_action_steps ADD COLUMN llm_step_id TEXT CHECK (
    (llm_step_id IS NULL) = (call_id IS NULL)
    AND (llm_step_id IS NULL OR LENGTH(TRIM(llm_step_id)) > 0)
);

-- The provider's own turn, held exactly as it arrived (an OpenAI reasoning item
-- keeps `encrypted_content`, an Anthropic thinking block keeps its signature),
-- so a later turn can hand it back. It belongs to the step that produced it, not
-- to `runtime_state_checkpoint`: that column is rewritten with the whole history
-- on every step, so storing turns there would grow the store with the square of
-- the step count.
ALTER TABLE agent_action_steps ADD COLUMN provider_turn TEXT CHECK (
    provider_turn IS NULL
    OR (step_type = 'llm_output' AND json_valid(provider_turn))
);
