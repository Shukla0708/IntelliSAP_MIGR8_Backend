-- ============================================================
-- Migration: AI-suggested validation rules catalog + rule_source
-- ============================================================
-- Adds:
--   validation_fields.rule_source          - user | ai | default
--   validation_rule_templates              - curated SAP rule catalog
--
-- Seed rows: scripts/apply_004_rule_templates_migration.py
--   (in-code fallback in services/rule_templates.py if the table is empty)
--
-- Safe to re-run: uses IF NOT EXISTS / ADD COLUMN IF NOT EXISTS.
-- ============================================================

BEGIN;

ALTER TABLE validation_fields
    ADD COLUMN IF NOT EXISTS rule_source TEXT NOT NULL DEFAULT 'default';

CREATE TABLE IF NOT EXISTS validation_rule_templates (
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

CREATE INDEX IF NOT EXISTS idx_rule_templates_active
    ON validation_rule_templates(active);

COMMIT;
