-- 退役した hard Plan / Goal Worker のスキーマを削除する。
-- plan テーブルは子から親の順に落とし、FK の宙吊りを作らない。
DROP TABLE IF EXISTS action_completed_goals;
DROP TABLE IF EXISTS action_requirements;
DROP TABLE IF EXISTS action_goals;
DROP TABLE IF EXISTS action_check_items;
DROP TABLE IF EXISTS action_desires;

-- DROP COLUMN は対象列に索引が残っていると失敗するため先に落とす。
DROP INDEX IF EXISTS idx_agent_action_steps_requirement_handle;

ALTER TABLE agent_action_steps DROP COLUMN requirement_handle;
ALTER TABLE agent_action_steps DROP COLUMN parallel_group_id;
ALTER TABLE agent_action_steps DROP COLUMN parallel_depth;
ALTER TABLE agent_action_steps DROP COLUMN parallel_index;
