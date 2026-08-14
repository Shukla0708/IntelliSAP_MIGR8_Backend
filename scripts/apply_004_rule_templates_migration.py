"""Apply migrations/004_validation_rule_templates.sql and seed the catalog."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from config import settings
from services.rule_templates import seed_templates

engine = create_engine(settings.database_url)
sql = (ROOT / "migrations" / "004_validation_rule_templates.sql").read_text(encoding="utf-8")

raw = engine.raw_connection()
try:
    raw.autocommit = True
    with raw.cursor() as cur:
        cur.execute(sql)
finally:
    raw.close()

with Session(engine) as session:
    count = seed_templates(session)

with engine.connect() as conn:
    present = conn.execute(
        text(
            """
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'validation_fields' AND column_name = 'rule_source'
            """
        )
    ).fetchone()
    table = conn.execute(
        text(
            """
            SELECT COUNT(*) FROM validation_rule_templates
            """
        )
    ).scalar()

print("rule_source column present:", bool(present))
print("validation_rule_templates rows:", table, "(seeded", count, ")")
engine.dispose()
