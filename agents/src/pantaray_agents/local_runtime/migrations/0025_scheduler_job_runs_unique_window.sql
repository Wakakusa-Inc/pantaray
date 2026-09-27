CREATE UNIQUE INDEX IF NOT EXISTS idx_scheduler_job_runs_unique_window
ON scheduler_job_runs(job_name, logical_window_start);
