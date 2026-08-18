-- Production-ready schema (005).
-- Note: 003_comparison_runs.sql and 003_run_progress.sql both used 003; new changes are 005+.

ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'member';
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE;

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS user_invites (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    email TEXT NOT NULL UNIQUE,
    invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
    used_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS learned_field_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    canonical_key TEXT NOT NULL UNIQUE,
    aliases TEXT DEFAULT '',
    org_id UUID,
    active BOOLEAN DEFAULT TRUE,
    flag_mandatory BOOLEAN DEFAULT FALSE,
    flag_null BOOLEAN DEFAULT FALSE,
    flag_email BOOLEAN DEFAULT FALSE,
    flag_mobile BOOLEAN DEFAULT FALSE,
    flag_date BOOLEAN DEFAULT FALSE,
    flag_special_chars BOOLEAN DEFAULT FALSE,
    case_format TEXT,
    data_type TEXT DEFAULT 'string',
    max_length INT,
    decimal_length INT,
    regex TEXT,
    regex_prompt TEXT,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    use_count INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS learned_field_mappings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_canonical TEXT NOT NULL UNIQUE,
    sap_table TEXT NOT NULL,
    sap_field TEXT NOT NULL,
    org_id UUID,
    active BOOLEAN DEFAULT TRUE,
    updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
    updated_at TIMESTAMPTZ DEFAULT now(),
    use_count INT DEFAULT 0
);

CREATE TABLE IF NOT EXISTS llm_response_cache (
    prompt_hash VARCHAR(64) PRIMARY KEY,
    model_id TEXT NOT NULL,
    response_text TEXT NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS embedding_cache (
    text_hash VARCHAR(64) PRIMARY KEY,
    model_id TEXT NOT NULL,
    vector JSONB NOT NULL,
    created_at TIMESTAMPTZ DEFAULT now()
);

CREATE TABLE IF NOT EXISTS llm_usage_log (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    created_at TIMESTAMPTZ DEFAULT now(),
    user_id UUID REFERENCES users(id) ON DELETE SET NULL,
    purpose TEXT NOT NULL DEFAULT 'generic',
    model_id TEXT NOT NULL,
    input_tokens INT DEFAULT 0,
    output_tokens INT DEFAULT 0,
    latency_ms INT DEFAULT 0,
    cache_hit BOOLEAN DEFAULT FALSE,
    estimated_usd NUMERIC(12, 6) DEFAULT 0
);
