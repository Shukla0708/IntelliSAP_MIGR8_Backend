"""Add progress columns to validation_runs if missing."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from config import settings

engine = create_engine(settings.database_url)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS processed_rows INT DEFAULT 0"))
    conn.execute(text("ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS total_rows INT DEFAULT 0"))
    conn.execute(text("ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS error_message TEXT"))
    rows = conn.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'validation_runs'
              AND column_name IN ('processed_rows', 'total_rows', 'error_message')
            ORDER BY column_name
            """
        )
    ).fetchall()
    print("progress columns:", [row[0] for row in rows])
