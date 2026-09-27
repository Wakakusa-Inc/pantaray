CREATE INDEX idx_jobs_user_queued_schedule_type
ON jobs(user_id, scheduled_at ASC, job_type)
WHERE status = 'queued';
