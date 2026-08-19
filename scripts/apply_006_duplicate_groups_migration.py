"""Apply 006_duplicate_groups.sql against DATABASE_URL."""
from pathlib import Path

from sqlalchemy import text

from db.database import engine

SQL_PATH = Path(__file__).resolve().parents[1] / "migrations" / "006_duplicate_groups.sql"


def main() -> None:
    sql = SQL_PATH.read_text(encoding="utf-8")
    with engine.begin() as conn:
        conn.execute(text(sql))
    print("applied", SQL_PATH.name)


if __name__ == "__main__":
    main()
