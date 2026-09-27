ALTER TABLE jobs ADD COLUMN logical_key TEXT;

UPDATE jobs
SET logical_key = (
    SELECT json_extract(job_payloads.payload_json, '$.action_id')
    FROM job_payloads
    WHERE job_payloads.job_id = jobs.job_id
)
WHERE job_type = 'execute_action' AND logical_key IS NULL;

CREATE INDEX idx_jobs_type_logical_key ON jobs(job_type, logical_key);
