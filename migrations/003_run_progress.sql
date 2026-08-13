-- Progress columns so the UI can poll large validation jobs.
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS processed_rows INT DEFAULT 0;
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS total_rows INT DEFAULT 0;
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS error_message TEXT;
