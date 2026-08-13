"""Apply migrations/003_comparison_runs.sql against DATABASE_URL.

Depends on final_mapping.key, which apply_002_field_mapping_migration.py adds.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from config import settings

engine = create_engine(settings.database_url)

with engine.connect() as conn:
    has_key_column = bool(
        conn.execute(
            text(
                """
                SELECT 1 FROM information_schema.columns
                WHERE table_name = 'final_mapping' AND column_name = 'key'
                """
            )
        ).fetchone()
    )

if not has_key_column:
    sys.exit(
        "final_mapping.key is missing — run scripts/apply_002_field_mapping_migration.py first."
    )

sql = (ROOT / "migrations" / "003_comparison_runs.sql").read_text(encoding="utf-8")

# psycopg2 needs the raw connection for multi-statement SQL scripts
raw = engine.raw_connection()
try:
    raw.autocommit = True
    with raw.cursor() as cur:
        cur.execute(sql)
finally:
    raw.close()

with engine.connect() as conn:
    tables = conn.execute(
        text(
            """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_name IN ('comparison_runs', 'comparison_discrepancies')
            """
        )
    ).fetchall()

print("comparison tables present:", sorted(row[0] for row in tables))
