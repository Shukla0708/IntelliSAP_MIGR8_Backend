from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from config import settings

# Remote RDS (e.g. ap-southeast-2) adds ~150–300ms per round trip. Reuse
# connections (LIFO) and skip pool_pre_ping so simple APIs are not 2x RTT.
_connect_args: dict = {}
if settings.database_url.startswith("postgresql"):
    _connect_args = {
        "connect_timeout": 5,
        "keepalives": 1,
        "keepalives_idle": 30,
        "keepalives_interval": 10,
        "keepalives_count": 3,
    }

engine = create_engine(
    settings.database_url,
    pool_size=8,
    max_overflow=8,
    pool_recycle=180,
    pool_pre_ping=False,
    pool_use_lifo=True,
    connect_args=_connect_args,
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
