-- ============================================================
-- Migration: preload vs postload comparison module
-- ============================================================
-- Adds comparison_runs + comparison_discrepancies.
--
-- The composite business key comes from final_mapping.key, which
-- 002_field_mapping_key_and_number_range.sql adds — run that first. This
-- migration only adds the partial index the comparison lookups use.
--
-- Safe to re-run: uses IF NOT EXISTS throughout.
-- Apply: psql "$DATABASE_URL" -f migrations/003_comparison_runs.sql
-- ============================================================

BEGIN;

-- 1) Lookup index for the composite business key flag
CREATE INDEX IF NOT EXISTS idx_final_mapping_key
    ON final_mapping(mapping_id) WHERE key = true;

-- 2) Comparison runs
CREATE TABLE IF NOT EXISTS comparison_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES validation_projects(id) ON DELETE CASCADE,
    name                VARCHAR(120) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft','running','completed','failed')),

    mapping_id          UUID REFERENCES mappings(id) ON DELETE SET NULL,
    business_key_columns_preload    JSONB NOT NULL DEFAULT '[]',
    business_key_columns_postload   JSONB NOT NULL DEFAULT '[]',

    preload_filename    TEXT,
    preload_s3_key      TEXT,
    postload_filename   TEXT,
    postload_s3_key     TEXT,
    result_s3_key       TEXT,

    total_preload_rows  INT DEFAULT 0,
    total_postload_rows INT DEFAULT 0,
    matched_records     INT DEFAULT 0,
    different_count     INT DEFAULT 0,
    missing_count       INT DEFAULT 0,
    match_rate          NUMERIC(5,2) DEFAULT 0,

    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ran_at              TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,

    CONSTRAINT uq_comparison_runs_project_name UNIQUE (project_id, name)
);

CREATE INDEX IF NOT EXISTS idx_comparison_runs_project_id ON comparison_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_comparison_runs_status ON comparison_runs(status);

-- 3) Capped discrepancy list (top 50 per run)
CREATE TABLE IF NOT EXISTS comparison_discrepancies (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES comparison_runs(id) ON DELETE CASCADE,
    row_number          INT NOT NULL,
    business_key        TEXT NOT NULL,
    field_name          TEXT NOT NULL,
    field_italic        BOOLEAN NOT NULL DEFAULT false,
    preload_value       TEXT,
    postload_value      TEXT,
    difference_type     TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'warning'
                         CHECK (severity IN ('error','warning','info')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_comparison_discrepancies_run_id
    ON comparison_discrepancies(run_id);

COMMIT;
