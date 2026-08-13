-- ============================================================
-- MIGR8 AI — Validation module schema
-- ============================================================

CREATE EXTENSION IF NOT EXISTS "pgcrypto"; -- for gen_random_uuid()

-- ------------------------------------------------------------
-- Users (backs /register and /sign-in)
-- ------------------------------------------------------------
CREATE TABLE users (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    full_name       TEXT NOT NULL,
    email           TEXT NOT NULL UNIQUE,
    password_hash   TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ------------------------------------------------------------
-- Projects — one migration project owns many validation runs.
-- This is what /validation's "previous runs for this project" list is scoped to.
-- ------------------------------------------------------------
CREATE TABLE validation_projects (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name            TEXT NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_projects_user_id ON validation_projects(user_id);

-- ------------------------------------------------------------
-- Runs — one upload -> configure -> execute cycle
-- ------------------------------------------------------------
CREATE TABLE validation_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES validation_projects(id) ON DELETE CASCADE,
    name                VARCHAR(120) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft','rules_configured','running','completed','failed')),

    source_filename     TEXT,
    source_s3_key       TEXT,
    result_s3_key       TEXT,

    total_records       INT DEFAULT 0,
    valid_rows          INT DEFAULT 0,
    invalid_rows        INT DEFAULT 0,
    total_errors        INT DEFAULT 0,
    critical_errors     INT DEFAULT 0,
    health_score        NUMERIC(5,2) DEFAULT 0,

    errors_by_type      JSONB DEFAULT '[]',
    errors_by_field     JSONB DEFAULT '[]',

    processed_rows      INT DEFAULT 0,
    total_rows          INT DEFAULT 0,
    error_message       TEXT,

    created_by          UUID REFERENCES users(id),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    ran_at              TIMESTAMPTZ,
    completed_at        TIMESTAMPTZ,

    CONSTRAINT uq_validation_runs_project_name UNIQUE (project_id, name)
);

CREATE INDEX idx_runs_project_id ON validation_runs(project_id);
CREATE INDEX idx_runs_status ON validation_runs(status);

-- ------------------------------------------------------------
-- Field-level rule configuration — one row per uploaded column
-- ------------------------------------------------------------
CREATE TABLE validation_fields (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
    field_name          TEXT NOT NULL,
    column_index        INT NOT NULL,

    flag_key            BOOLEAN NOT NULL DEFAULT false,
    flag_mandatory      BOOLEAN NOT NULL DEFAULT false,
    flag_null           BOOLEAN NOT NULL DEFAULT false,
    flag_email          BOOLEAN NOT NULL DEFAULT false,
    flag_mobile         BOOLEAN NOT NULL DEFAULT false,
    flag_date           BOOLEAN NOT NULL DEFAULT false,
    flag_special_chars  BOOLEAN NOT NULL DEFAULT false,

    case_format         TEXT CHECK (case_format IN ('uppercase','lowercase','camelCase')),
    data_type           TEXT NOT NULL DEFAULT 'string'
                         CHECK (data_type IN ('char','int','decimal','string','boolean')),
    max_length          INT,
    decimal_length      INT,

    regex               TEXT,       -- final AI-generated pattern actually applied
    regex_prompt        TEXT,       -- the plain-English prompt the user typed (Groq input)

    UNIQUE (run_id, field_name)
);

CREATE INDEX idx_fields_run_id ON validation_fields(run_id);

-- ------------------------------------------------------------
-- Capped exception list (~50-60 shown on the results page)
-- ------------------------------------------------------------
CREATE TABLE validation_exceptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES validation_runs(id) ON DELETE CASCADE,
    row_number          INT NOT NULL,
    field_name          TEXT NOT NULL,
    actual_value        TEXT,
    expected_value      TEXT,
    error_type          TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'error' CHECK (severity IN ('error','warning')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_exceptions_run_id ON validation_exceptions(run_id);

-- ------------------------------------------------------------
-- Field mapping — source field list + target SAP field list ->
-- embedding-ranked candidates, re-scored/explained by an LLM.
-- ------------------------------------------------------------
CREATE TABLE mappings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES validation_projects(id) ON DELETE CASCADE,
    mapping_name        TEXT NOT NULL DEFAULT 'New field mapping run',
    status              TEXT NOT NULL DEFAULT 'processing'
                         CHECK (status IN ('processing','completed','failed')),

    source_filename     TEXT,
    source_s3_key       TEXT,
    target_filename     TEXT,
    target_s3_key       TEXT,

    total_source_fields INT DEFAULT 0,
    mapped_fields       INT DEFAULT 0,      -- source fields that received >=1 candidate

    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_updated_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_mappings_project_id ON mappings(project_id);

-- Top-3 candidates per source field, collapsed into one JSON array per row.
-- Each element: {sap_table, sap_field, target_description, embedding_score,
-- datatype_match_score, confidence_score, reasoning}.
CREATE TABLE mapping_temp (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_id          UUID NOT NULL REFERENCES mappings(id) ON DELETE CASCADE,

    source_field        TEXT NOT NULL,
    mapping             JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX idx_mapping_temp_mapping_id ON mapping_temp(mapping_id);

-- User-confirmed source -> target field mapping, one row per confirmed source field.
CREATE TABLE final_mapping (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_id          UUID NOT NULL REFERENCES mappings(id) ON DELETE CASCADE,

    source_field        TEXT NOT NULL,
    target_field        TEXT NOT NULL,      -- "{sap_table}.{sap_field}"

    UNIQUE (mapping_id, source_field)
);

CREATE INDEX idx_final_mapping_mapping_id ON final_mapping(mapping_id);

-- ------------------------------------------------------------
-- Preload vs postload comparison runs
-- ------------------------------------------------------------
CREATE TABLE comparison_runs (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id              UUID NOT NULL REFERENCES validation_projects(id) ON DELETE CASCADE,
    name                    VARCHAR(120) NOT NULL,
    status                  TEXT NOT NULL DEFAULT 'draft'
                             CHECK (status IN ('draft','running','completed','failed')),

    preload_filename        TEXT,
    preload_s3_key          TEXT,
    postload_filename       TEXT,
    postload_s3_key         TEXT,
    result_s3_key           TEXT,

    mapping_id              UUID REFERENCES mappings(id) ON DELETE SET NULL,
    join_keys               JSONB DEFAULT '[]',

    processed_rows          INT DEFAULT 0,
    total_rows              INT DEFAULT 0,
    error_message           TEXT,

    matched_records         INT DEFAULT 0,
    different_count         INT DEFAULT 0,
    missing_count           INT DEFAULT 0,
    extra_count             INT DEFAULT 0,
    match_rate              NUMERIC(5, 2) DEFAULT 0,

    created_by              UUID REFERENCES users(id),
    created_at              TIMESTAMPTZ NOT NULL DEFAULT now(),
    ran_at                  TIMESTAMPTZ,
    completed_at            TIMESTAMPTZ,

    CONSTRAINT uq_comparison_runs_project_name UNIQUE (project_id, name)
);

CREATE INDEX idx_comparison_runs_project_id ON comparison_runs(project_id);
CREATE INDEX idx_comparison_runs_status ON comparison_runs(status);

CREATE TABLE comparison_exceptions (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    run_id              UUID NOT NULL REFERENCES comparison_runs(id) ON DELETE CASCADE,
    row_number          INT NOT NULL,
    business_key        TEXT NOT NULL,
    field_name          TEXT NOT NULL,
    preload_value       TEXT,
    postload_value      TEXT,
    difference_type     TEXT NOT NULL,
    severity            TEXT NOT NULL DEFAULT 'warning'
                         CHECK (severity IN ('error','warning','info')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX idx_comparison_exceptions_run_id ON comparison_exceptions(run_id);
