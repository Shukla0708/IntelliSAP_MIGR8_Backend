ALTER TABLE validation_runs
    ADD COLUMN IF NOT EXISTS duplicate_groups JSONB;
