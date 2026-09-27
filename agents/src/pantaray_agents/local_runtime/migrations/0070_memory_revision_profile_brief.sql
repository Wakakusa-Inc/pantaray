ALTER TABLE memory_revisions
ADD COLUMN profile_brief TEXT
CHECK (profile_brief IS NULL OR length(trim(profile_brief)) > 0);

UPDATE memory_revisions
SET profile_brief = (
    SELECT facts.facts_profile_brief
    FROM memory_nodes AS nodes
    JOIN agent_facts AS facts
      ON facts.user_id = nodes.user_id
     AND facts.fact_id = nodes.source_record_id
     AND facts.status = 'success'
     AND facts.structured_fact_sha256 = memory_revisions.content_sha256
    WHERE nodes.user_id = memory_revisions.user_id
      AND nodes.node_id = memory_revisions.node_id
      AND nodes.source_type = 'fact'
      AND nodes.current_revision_id = memory_revisions.revision_id
      AND facts.facts_profile_brief IS NOT NULL
      AND trim(facts.facts_profile_brief) != ''
    ORDER BY facts.updated_at DESC, facts.fact_id DESC
    LIMIT 1
)
WHERE profile_brief IS NULL;

UPDATE memory_revisions
SET profile_brief = (
    SELECT state.insight_profile_brief
    FROM memory_nodes AS nodes
    JOIN agent_long_term_insight_state AS state
      ON state.user_id = nodes.user_id
     AND state.sha256 = memory_revisions.content_sha256
    WHERE nodes.user_id = memory_revisions.user_id
      AND nodes.node_id = memory_revisions.node_id
      AND nodes.source_type = 'long_term_insight'
      AND nodes.source_record_id = memory_revisions.user_id
      AND nodes.current_revision_id = memory_revisions.revision_id
      AND state.insight_profile_brief IS NOT NULL
      AND trim(state.insight_profile_brief) != ''
    LIMIT 1
)
WHERE profile_brief IS NULL;
