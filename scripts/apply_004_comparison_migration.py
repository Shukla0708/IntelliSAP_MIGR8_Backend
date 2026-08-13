"""Add any missing comparison_runs columns (create_all does not ALTER existing tables)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from config import settings

STATEMENTS = [
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS preload_filename TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS preload_s3_key TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS postload_filename TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS postload_s3_key TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS result_s3_key TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS mapping_id UUID REFERENCES mappings(id) ON DELETE SET NULL",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS join_keys JSONB DEFAULT '[]'",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS processed_rows INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS total_rows INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS error_message TEXT",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS matched_records INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS different_count INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS missing_count INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS extra_count INT DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS match_rate NUMERIC(5, 2) DEFAULT 0",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS created_by UUID REFERENCES users(id)",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS ran_at TIMESTAMPTZ",
    "ALTER TABLE comparison_runs ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ",
]

engine = create_engine(settings.database_url)
with engine.begin() as conn:
    for sql in STATEMENTS:
        conn.execute(text(sql))
    rows = conn.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'comparison_runs'
            ORDER BY column_name
            """
        )
    ).fetchall()
    print("comparison_runs columns:", [row[0] for row in rows])
