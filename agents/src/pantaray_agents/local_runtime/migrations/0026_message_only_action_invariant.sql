UPDATE agent_suggestions
SET
    user_reaction = NULL,
    accepted_at = NULL,
    rejected_at = NULL,
    action_status = NULL,
    action_failure_code = NULL,
    action_failure_stage = NULL,
    action_failure_message_public = NULL,
    action_request_payload = NULL,
    action_process_id = NULL,
    action_execution_id = NULL,
    action_command_id = NULL,
    action_started_at = NULL,
    updated_at = strftime('%Y-%m-%dT%H:%M:%fZ', 'now')
WHERE interaction_contract = 'message_only'
  AND (
      user_reaction IS NOT NULL
      OR accepted_at IS NOT NULL
      OR rejected_at IS NOT NULL
      OR action_status IS NOT NULL
      OR action_failure_code IS NOT NULL
      OR action_failure_stage IS NOT NULL
      OR action_failure_message_public IS NOT NULL
      OR action_request_payload IS NOT NULL
      OR action_process_id IS NOT NULL
      OR action_execution_id IS NOT NULL
      OR action_command_id IS NOT NULL
      OR action_started_at IS NOT NULL
  );

DELETE FROM agent_actions
WHERE suggestion_id IN (
    SELECT suggestion_id
    FROM agent_suggestions
    WHERE interaction_contract = 'message_only'
);

UPDATE agent_suggestion_history
SET
    user_reaction = NULL,
    accepted_at = NULL,
    rejected_at = NULL,
    action_status = NULL,
    action_failure_code = NULL,
    action_failure_stage = NULL,
    action_failure_message_public = NULL,
    action_request_payload_present = 0,
    action_id = NULL,
    action_created_at = NULL,
    action_updated_at = NULL,
    final_output = NULL
WHERE interaction_contract = 'message_only'
  AND (
      user_reaction IS NOT NULL
      OR accepted_at IS NOT NULL
      OR rejected_at IS NOT NULL
      OR action_status IS NOT NULL
      OR action_failure_code IS NOT NULL
      OR action_failure_stage IS NOT NULL
      OR action_failure_message_public IS NOT NULL
      OR action_request_payload_present != 0
      OR action_id IS NOT NULL
      OR action_created_at IS NOT NULL
      OR action_updated_at IS NOT NULL
      OR final_output IS NOT NULL
  );

DROP TRIGGER IF EXISTS reject_message_only_action_lane_insert;
DROP TRIGGER IF EXISTS reject_message_only_action_lane_update;
DROP TRIGGER IF EXISTS reject_message_only_agent_action_insert;
DROP TRIGGER IF EXISTS reject_message_only_agent_action_update;
DROP TRIGGER IF EXISTS reject_message_only_history_action_lane_insert;
DROP TRIGGER IF EXISTS reject_message_only_history_action_lane_update;

CREATE TRIGGER reject_message_only_action_lane_insert
BEFORE INSERT ON agent_suggestions
WHEN NEW.interaction_contract = 'message_only'
 AND (
     NEW.user_reaction IS NOT NULL
     OR NEW.accepted_at IS NOT NULL
     OR NEW.rejected_at IS NOT NULL
     OR NEW.action_status IS NOT NULL
     OR NEW.action_failure_code IS NOT NULL
     OR NEW.action_failure_stage IS NOT NULL
     OR NEW.action_failure_message_public IS NOT NULL
     OR NEW.action_request_payload IS NOT NULL
     OR NEW.action_process_id IS NOT NULL
     OR NEW.action_execution_id IS NOT NULL
     OR NEW.action_command_id IS NOT NULL
     OR NEW.action_started_at IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'message_only suggestions must not carry action lane state');
END;

CREATE TRIGGER reject_message_only_action_lane_update
BEFORE UPDATE ON agent_suggestions
WHEN NEW.interaction_contract = 'message_only'
 AND (
     NEW.user_reaction IS NOT NULL
     OR NEW.accepted_at IS NOT NULL
     OR NEW.rejected_at IS NOT NULL
     OR NEW.action_status IS NOT NULL
     OR NEW.action_failure_code IS NOT NULL
     OR NEW.action_failure_stage IS NOT NULL
     OR NEW.action_failure_message_public IS NOT NULL
     OR NEW.action_request_payload IS NOT NULL
     OR NEW.action_process_id IS NOT NULL
     OR NEW.action_execution_id IS NOT NULL
     OR NEW.action_command_id IS NOT NULL
     OR NEW.action_started_at IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'message_only suggestions must not carry action lane state');
END;

CREATE TRIGGER reject_message_only_agent_action_insert
BEFORE INSERT ON agent_actions
WHEN EXISTS (
    SELECT 1
    FROM agent_suggestions AS s
    WHERE s.suggestion_id = NEW.suggestion_id
      AND s.interaction_contract = 'message_only'
)
BEGIN
    SELECT RAISE(ABORT, 'message_only suggestions must not own action rows');
END;

CREATE TRIGGER reject_message_only_agent_action_update
BEFORE UPDATE ON agent_actions
WHEN EXISTS (
    SELECT 1
    FROM agent_suggestions AS s
    WHERE s.suggestion_id = NEW.suggestion_id
      AND s.interaction_contract = 'message_only'
)
BEGIN
    SELECT RAISE(ABORT, 'message_only suggestions must not own action rows');
END;

CREATE TRIGGER reject_message_only_history_action_lane_insert
BEFORE INSERT ON agent_suggestion_history
WHEN NEW.interaction_contract = 'message_only'
 AND (
     NEW.user_reaction IS NOT NULL
     OR NEW.accepted_at IS NOT NULL
     OR NEW.rejected_at IS NOT NULL
     OR NEW.action_status IS NOT NULL
     OR NEW.action_failure_code IS NOT NULL
     OR NEW.action_failure_stage IS NOT NULL
     OR NEW.action_failure_message_public IS NOT NULL
     OR NEW.action_request_payload_present != 0
     OR NEW.action_id IS NOT NULL
     OR NEW.action_created_at IS NOT NULL
     OR NEW.action_updated_at IS NOT NULL
     OR NEW.final_output IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'message_only history rows must not carry action lane state');
END;

CREATE TRIGGER reject_message_only_history_action_lane_update
BEFORE UPDATE ON agent_suggestion_history
WHEN NEW.interaction_contract = 'message_only'
 AND (
     NEW.user_reaction IS NOT NULL
     OR NEW.accepted_at IS NOT NULL
     OR NEW.rejected_at IS NOT NULL
     OR NEW.action_status IS NOT NULL
     OR NEW.action_failure_code IS NOT NULL
     OR NEW.action_failure_stage IS NOT NULL
     OR NEW.action_failure_message_public IS NOT NULL
     OR NEW.action_request_payload_present != 0
     OR NEW.action_id IS NOT NULL
     OR NEW.action_created_at IS NOT NULL
     OR NEW.action_updated_at IS NOT NULL
     OR NEW.final_output IS NOT NULL
 )
BEGIN
    SELECT RAISE(ABORT, 'message_only history rows must not carry action lane state');
END;
