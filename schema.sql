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
