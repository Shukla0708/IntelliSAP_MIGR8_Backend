"""Apply migrations/002_field_mapping_key_and_number_range.sql against DATABASE_URL."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from config import settings

sql = (ROOT / "migrations" / "002_field_mapping_key_and_number_range.sql").read_text(encoding="utf-8")
engine = create_engine(settings.database_url)

raw = engine.raw_connection()
try:
    raw.autocommit = True
    with raw.cursor() as cur:
        cur.execute(sql)
finally:
    raw.close()

checks = [
    ("mappings", "number_range_type"),
    ("mapping_temp", "key_field"),
    ("final_mapping", "key"),
]

with engine.connect() as conn:
    for table, column in checks:
        present = bool(
            conn.execute(
                text(
                    """
                    SELECT 1 FROM information_schema.columns
                    WHERE table_name = :table AND column_name = :column
                    """
                ),
                {"table": table, "column": column},
            ).fetchone()
        )
        print(f"{table}.{column}: {present}")
