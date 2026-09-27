INSERT OR IGNORE INTO agent_fact_structuring_runs (
    fact_run_id,
    user_id,
    fact_id,
    status,
    base_storage_path,
    base_sha256,
    final_storage_path,
    final_sha256,
    facts_profile_brief,
    error,
    prompt_name,
    prompt_version,
    source_insight_ids,
    created_at,
    updated_at
)
SELECT
    'legacy-' || fact_id,
    user_id,
    fact_id,
    'success',
    structured_fact_storage_path,
    structured_fact_sha256,
    structured_fact_storage_path,
    structured_fact_sha256,
    facts_profile_brief,
    NULL,
    prompt_name,
    prompt_version,
    COALESCE(source_insight_ids, '[]'),
    created_at,
    updated_at
FROM agent_facts
WHERE status = 'success'
  AND facts_profile_brief IS NOT NULL
  AND TRIM(facts_profile_brief) != '';
