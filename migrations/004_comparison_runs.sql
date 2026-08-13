CREATE TABLE IF NOT EXISTS comparison_runs (
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

CREATE INDEX IF NOT EXISTS idx_comparison_runs_project_id ON comparison_runs(project_id);
CREATE INDEX IF NOT EXISTS idx_comparison_runs_status ON comparison_runs(status);

CREATE TABLE IF NOT EXISTS comparison_exceptions (
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

CREATE INDEX IF NOT EXISTS idx_comparison_exceptions_run_id ON comparison_exceptions(run_id);
