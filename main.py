from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from urllib.parse import unquote
import logging
import time
import uuid

from sqlalchemy import inspect, text

from auth import get_current_user
from config import settings
from db.database import engine
from db.models import Base, User
from errors import (
    http_exception_handler,
    unhandled_exception_handler,
    validation_exception_handler,
)
from logging_config import configure_logging, extra
from routers import admin, auth, chat, comparison, dashboard, mapping, projects, validation
from services import job_queue, s3_service

configure_logging(json_logs=settings.json_logs)
logger = logging.getLogger("migr8.http")

docs_url = None if settings.is_production() else "/docs"
redoc_url = None if settings.is_production() else "/redoc"

app = FastAPI(
    title="MIGR8 AI — Validation API",
    docs_url=docs_url,
    redoc_url=redoc_url,
    openapi_url=None if settings.is_production() else "/openapi.json",
)

_CORS_ORIGINS = settings.cors_origin_list()

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["X-Request-ID", "X-Response-Time"],
)

app.add_exception_handler(HTTPException, http_exception_handler)
app.add_exception_handler(RequestValidationError, validation_exception_handler)
app.add_exception_handler(Exception, unhandled_exception_handler)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(validation.router)
app.include_router(mapping.router)
app.include_router(comparison.router)
app.include_router(chat.router)
app.include_router(dashboard.router)
app.include_router(admin.router)


@app.middleware("http")
async def request_context(request: Request, call_next):
    request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    request.state.request_id = request_id
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Response-Time"] = f"{elapsed_ms:.0f}ms"
    logger.info(
        "http_request",
        **extra(
            request_id=request_id,
            route=f"{request.method} {request.url.path}",
            duration_ms=round(elapsed_ms),
            user_id=getattr(request.state, "user_id", None),
        ),
    )
    return response


def _ensure_production_schema() -> None:
    statements = [
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS role VARCHAR(32) DEFAULT 'member'",
        "ALTER TABLE users ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE",
        """
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL DEFAULT '',
            updated_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS user_invites (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            email TEXT NOT NULL UNIQUE,
            invited_by UUID REFERENCES users(id) ON DELETE SET NULL,
            used_at TIMESTAMPTZ,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS learned_field_rules (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            canonical_key TEXT NOT NULL UNIQUE,
            aliases TEXT DEFAULT '',
            org_id UUID,
            active BOOLEAN DEFAULT TRUE,
            flag_mandatory BOOLEAN DEFAULT FALSE,
            flag_null BOOLEAN DEFAULT FALSE,
            flag_email BOOLEAN DEFAULT FALSE,
            flag_mobile BOOLEAN DEFAULT FALSE,
            flag_date BOOLEAN DEFAULT FALSE,
            flag_special_chars BOOLEAN DEFAULT FALSE,
            case_format TEXT,
            data_type TEXT DEFAULT 'string',
            max_length INT,
            decimal_length INT,
            regex TEXT,
            regex_prompt TEXT,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ DEFAULT now(),
            use_count INT DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS learned_field_mappings (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            source_canonical TEXT NOT NULL UNIQUE,
            sap_table TEXT NOT NULL,
            sap_field TEXT NOT NULL,
            org_id UUID,
            active BOOLEAN DEFAULT TRUE,
            updated_by UUID REFERENCES users(id) ON DELETE SET NULL,
            updated_at TIMESTAMPTZ DEFAULT now(),
            use_count INT DEFAULT 0
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS llm_response_cache (
            prompt_hash VARCHAR(64) PRIMARY KEY,
            model_id TEXT NOT NULL,
            response_text TEXT NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS embedding_cache (
            text_hash VARCHAR(64) PRIMARY KEY,
            model_id TEXT NOT NULL,
            vector JSONB NOT NULL,
            created_at TIMESTAMPTZ DEFAULT now()
        )
        """,
        "ALTER TABLE validation_runs ADD COLUMN IF NOT EXISTS duplicate_groups JSONB",
        """
        CREATE TABLE IF NOT EXISTS llm_usage_log (
            id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            created_at TIMESTAMPTZ DEFAULT now(),
            user_id UUID REFERENCES users(id) ON DELETE SET NULL,
            purpose TEXT NOT NULL DEFAULT 'generic',
            model_id TEXT NOT NULL,
            input_tokens INT DEFAULT 0,
            output_tokens INT DEFAULT 0,
            latency_ms INT DEFAULT 0,
            cache_hit BOOLEAN DEFAULT FALSE,
            estimated_usd NUMERIC(12, 6) DEFAULT 0
        )
        """,
    ]
    try:
        with engine.begin() as conn:
            for sql in statements:
                conn.execute(text(sql))
            if settings.admin_email:
                conn.execute(
                    text(
                        "UPDATE users SET role = 'admin' "
                        "WHERE lower(email) = lower(:email)"
                    ),
                    {"email": settings.admin_email},
                )
    except Exception:
        logger.exception("Could not ensure production-ready schema")


@app.on_event("startup")
def on_startup():
    inspector = inspect(engine)
    if "users" not in inspector.get_table_names():
        Base.metadata.create_all(bind=engine)
    _ensure_production_schema()
    job_queue.start()


@app.on_event("shutdown")
def on_shutdown():
    job_queue.stop()


@app.get("/health")
def health():
    return {
        "status": "ok",
        "storage": s3_service.storage_mode(),
        "llm": "bedrock",
        "model": settings.bedrock_model_id,
        "embed_model": settings.bedrock_embed_model_id,
        "embedding_backend": settings.embedding_backend,
        "bedrock_region": settings.bedrock_region,
    }


@app.get("/ready")
def ready():
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception:
        return Response(status_code=503, content='{"status":"not_ready"}', media_type="application/json")
    return {"status": "ready", "storage": s3_service.storage_mode()}


@app.get("/api/local-files/{key:path}")
def serve_local_file(key: str, current_user: User = Depends(get_current_user)):
    del current_user
    if s3_service.storage_mode() != "local":
        raise HTTPException(404, "Local file serving is disabled (using S3)")
    decoded = unquote(key)
    try:
        data = s3_service.download_bytes(decoded)
    except FileNotFoundError:
        raise HTTPException(404, "File not found")
    filename = decoded.rsplit("/", 1)[-1] or "download.xlsx"
    return Response(
        content=data,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
