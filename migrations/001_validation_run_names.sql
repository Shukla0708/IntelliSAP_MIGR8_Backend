-- ============================================================
-- Migration: user-provided unique validation run names per project
-- ============================================================
-- Renames run_name → name (if needed), backfills duplicates,
-- drops the hardcoded default, enforces NOT NULL + VARCHAR(120),
-- and adds UNIQUE (project_id, name).
--
-- Safe to re-run: uses IF EXISTS / exception guards where needed.
-- Apply: psql "$DATABASE_URL" -f migrations/001_validation_run_names.sql
-- ============================================================

BEGIN;

-- 1) Rename legacy column if present
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'validation_runs' AND column_name = 'run_name'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'validation_runs' AND column_name = 'name'
    ) THEN
        ALTER TABLE validation_runs RENAME COLUMN run_name TO name;
    END IF;
END $$;

-- 2) Ensure column exists for DBs that somehow lack both (should not happen)
ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS name VARCHAR(120);

-- 3) Backfill empty / null names
UPDATE validation_runs
SET name = 'Unnamed run ' || LEFT(id::text, 8)
WHERE name IS NULL OR btrim(name) = '';

-- 4) Make duplicate (project_id, name) rows unique before adding constraint.
--    Keep the oldest row's name; append a short id to later duplicates.
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY project_id, btrim(name)
            ORDER BY created_at ASC NULLS LAST, id ASC
        ) AS rn
    FROM validation_runs
)
UPDATE validation_runs vr
SET name = LEFT(btrim(vr.name) || ' (' || LEFT(vr.id::text, 8) || ')', 120)
FROM ranked r
WHERE vr.id = r.id
  AND r.rn > 1;

-- 5) Drop hardcoded default (e.g. 'New validation run')
ALTER TABLE validation_runs ALTER COLUMN name DROP DEFAULT;

-- 6) Enforce length + NOT NULL
ALTER TABLE validation_runs
    ALTER COLUMN name TYPE VARCHAR(120) USING LEFT(btrim(name), 120),
    ALTER COLUMN name SET NOT NULL;

-- 7) Unique per project (idempotent)
DO $$
BEGIN
    ALTER TABLE validation_runs
        ADD CONSTRAINT uq_validation_runs_project_name UNIQUE (project_id, name);
EXCEPTION
    WHEN duplicate_object THEN NULL;
END $$;

COMMIT;
