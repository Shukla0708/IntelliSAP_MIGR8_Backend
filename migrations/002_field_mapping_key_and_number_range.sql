-- ============================================================
-- Migration: number-range choice + key-field tracking for field mapping
-- ============================================================
-- Adds:
--   mappings.number_range_type   - "internal" | "external", chosen when a
--                                   mapping run is started
--   mapping_temp.key_field       - whether this source field was flagged as
--                                   a key field in the uploaded source file
--   final_mapping.key            - carried over from mapping_temp.key_field
--                                   when a mapping is confirmed
--
-- Safe to re-run: uses IF NOT EXISTS.
-- Apply: psql "$DATABASE_URL" -f migrations/002_field_mapping_key_and_number_range.sql
-- ============================================================

BEGIN;

ALTER TABLE mappings ADD COLUMN IF NOT EXISTS number_range_type VARCHAR(20);

ALTER TABLE mapping_temp ADD COLUMN IF NOT EXISTS key_field BOOLEAN DEFAULT FALSE;

ALTER TABLE final_mapping ADD COLUMN IF NOT EXISTS key BOOLEAN DEFAULT FALSE;

COMMIT;
