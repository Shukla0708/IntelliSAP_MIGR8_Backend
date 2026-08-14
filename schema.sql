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
    rule_source         TEXT NOT NULL DEFAULT 'default'
                         CHECK (rule_source IN ('user','ai','default')),

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
    number_range_type   VARCHAR(20)          -- internal | external, chosen at run start
                         CHECK (number_range_type IN ('internal','external')),

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
    key_field           BOOLEAN DEFAULT false,  -- flagged as a key in the source file
    mapping             JSONB NOT NULL DEFAULT '[]'
);

CREATE INDEX idx_mapping_temp_mapping_id ON mapping_temp(mapping_id);

-- User-confirmed source -> target field mapping, one row per confirmed source field.
-- "key" is carried over from mapping_temp.key_field on confirm. Several fields may
-- carry key = true; together they form the composite business key used to join
-- preload and postload rows during comparison.
CREATE TABLE final_mapping (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    mapping_id          UUID NOT NULL REFERENCES mappings(id) ON DELETE CASCADE,

    source_field        TEXT NOT NULL,
    target_field        TEXT NOT NULL,      -- "{sap_table}.{sap_field}"
    key                 BOOLEAN DEFAULT false,

    UNIQUE (mapping_id, source_field)
);

CREATE INDEX idx_final_mapping_mapping_id ON final_mapping(mapping_id);
CREATE INDEX idx_final_mapping_key ON final_mapping(mapping_id) WHERE key = true;

-- ------------------------------------------------------------
-- Preload vs postload comparison — one upload pair -> execute cycle
-- ------------------------------------------------------------
CREATE TABLE comparison_runs (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    project_id          UUID NOT NULL REFERENCES validation_projects(id) ON DELETE CASCADE,
    name                VARCHAR(120) NOT NULL,
    status              TEXT NOT NULL DEFAULT 'draft'
                         CHECK (status IN ('draft','running','completed','failed')),

    -- NULL = compare columns that share a name in both files
    mapping_id          UUID REFERENCES mappings(id) ON DELETE SET NULL,
    -- Explicit composite key override used when no mapping is selected
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

CREATE INDEX idx_comparison_runs_project_id ON comparison_runs(project_id);
CREATE INDEX idx_comparison_runs_status ON comparison_runs(status);

-- ------------------------------------------------------------
-- Capped discrepancy list (top 50 rows shown on the review page)
-- ------------------------------------------------------------
CREATE TABLE comparison_discrepancies (
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

CREATE INDEX idx_comparison_discrepancies_run_id ON comparison_discrepancies(run_id);

-- ------------------------------------------------------------
-- Curated SAP rule catalog for "Apply rules with AI"
-- Embeddings are computed in memory from name + aliases (no pgvector).
-- Templates never set flag_key.
-- ------------------------------------------------------------
CREATE TABLE validation_rule_templates (
    id                      UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name                    TEXT NOT NULL UNIQUE,
    aliases                 TEXT NOT NULL DEFAULT '',
    flag_mandatory          BOOLEAN NOT NULL DEFAULT false,
    flag_null               BOOLEAN NOT NULL DEFAULT false,
    flag_email              BOOLEAN NOT NULL DEFAULT false,
    flag_mobile             BOOLEAN NOT NULL DEFAULT false,
    flag_date               BOOLEAN NOT NULL DEFAULT false,
    flag_special_chars      BOOLEAN NOT NULL DEFAULT false,
    case_format             TEXT CHECK (case_format IN ('uppercase','lowercase','camelCase')),
    data_type               TEXT NOT NULL DEFAULT 'string'
                             CHECK (data_type IN ('char','int','decimal','string','boolean')),
    max_length              INT,
    decimal_length          INT,
    regex_prompt            TEXT,
    priority                INT NOT NULL DEFAULT 100,
    active                  BOOLEAN NOT NULL DEFAULT true
);

CREATE INDEX idx_rule_templates_active ON validation_rule_templates(active);
