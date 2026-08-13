"""Apply migrations/001_validation_run_names.sql against DATABASE_URL."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text

from config import settings

sql = (ROOT / "migrations" / "001_validation_run_names.sql").read_text(encoding="utf-8")
engine = create_engine(settings.database_url)

# psycopg2 needs the raw connection for multi-statement SQL scripts
raw = engine.raw_connection()
try:
    raw.autocommit = True
    with raw.cursor() as cur:
        cur.execute(sql)
finally:
    raw.close()

with engine.connect() as conn:
    cols = conn.execute(
        text(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'validation_runs' AND column_name = 'name'
            """
        )
    ).fetchall()

print("migration applied; name column present:", bool(cols))
