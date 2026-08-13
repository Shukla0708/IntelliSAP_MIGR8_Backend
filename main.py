from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from urllib.parse import unquote

from db.database import engine
from db.models import Base
from routers import auth, projects, validation, mapping
from services import s3_service

app = FastAPI(title="MIGR8 AI — Validation API")

# Local frontend origins (localhost vs 127.0.0.1 are different for CORS).
# Axios "Network Error" on upload is often a blocked preflight from a missing origin.
_CORS_ORIGINS = [
    "http://localhost:3000",
    "http://127.0.0.1:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3001",
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["*"],
)

app.include_router(auth.router)
app.include_router(projects.router)
app.include_router(validation.router)
app.include_router(mapping.router)


@app.on_event("startup")
def on_startup():
    # For the hackathon: auto-create tables if they don't exist.
    # In practice, run schema.sql directly against Postgres instead.
    Base.metadata.create_all(bind=engine)


@app.get("/health")
def health():
    return {"status": "ok", "storage": s3_service.storage_mode()}


@app.get("/api/local-files/{key:path}")
def serve_local_file(key: str):
    """Hackathon download path when storage_backend is local (no S3)."""
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
