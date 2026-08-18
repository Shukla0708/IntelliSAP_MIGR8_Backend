"""Thin admin API — users, invites, learned rules, LLM spend, jobs, SAP health."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import func, text
from sqlalchemy.orm import Session

from auth import require_admin, user_out
from config import settings
from db.database import get_db
from db.models import (
    ComparisonRun,
    LearnedFieldMapping,
    LearnedFieldRule,
    LlmResponseCache,
    LlmUsageLog,
    Mapping,
    User,
    UserInvite,
    ValidationRun,
)
from services import app_settings, sap_mcp

router = APIRouter(prefix="/api/admin", tags=["admin"])


class InviteIn(BaseModel):
    email: str

    @field_validator("email")
    @classmethod
    def normalize(cls, value: str) -> str:
        cleaned = value.strip().lower()
        if "@" not in cleaned:
            raise ValueError("must be a valid email")
        return cleaned


class RoleIn(BaseModel):
    role: str

    @field_validator("role")
    @classmethod
    def allowed(cls, value: str) -> str:
        if value not in ("admin", "member"):
            raise ValueError("role must be admin or member")
        return value


class ActiveIn(BaseModel):
    isActive: bool


class InviteOnlyIn(BaseModel):
    inviteOnly: bool


class LearnedRulePatch(BaseModel):
    active: bool | None = None
    max_length: int | None = None
    data_type: str | None = None
    regex: str | None = None
    regex_prompt: str | None = None


class SapToggleIn(BaseModel):
    enabled: bool


@router.get("/users")
def list_users(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rows = db.query(User).order_by(User.created_at.desc()).all()
    return [
        {
            "id": str(u.id),
            "fullName": u.full_name,
            "email": u.email,
            "role": u.role or "member",
            "isActive": bool(u.is_active if u.is_active is not None else True),
            "createdAt": u.created_at.isoformat() if u.created_at else None,
        }
        for u in rows
    ]


@router.post("/users/invite")
def invite_user(payload: InviteIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    if db.query(User).filter(User.email == payload.email).first():
        raise HTTPException(status.HTTP_409_CONFLICT, "A user with this email already exists")
    existing = db.query(UserInvite).filter(UserInvite.email == payload.email).first()
    if existing:
        existing.used_at = None
        existing.invited_by = admin.id
    else:
        db.add(UserInvite(email=payload.email, invited_by=admin.id))
    db.commit()
    return {"ok": True, "email": payload.email}


@router.post("/users/{user_id}/role")
def set_role(user_id: str, payload: RoleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    user.role = payload.role
    db.commit()
    return user_out(user)


@router.post("/users/{user_id}/active")
def set_active(user_id: str, payload: ActiveIn, admin: User = Depends(require_admin), db: Session = Depends(get_db)):
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(404, "User not found")
    if user.id == admin.id and not payload.isActive:
        raise HTTPException(400, "You cannot disable your own account")
    user.is_active = payload.isActive
    db.commit()
    return user_out(user)


@router.get("/settings")
def get_settings(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return {
        "inviteOnly": app_settings.invite_only(db),
        "sapMcpEnabled": app_settings.sap_mcp_enabled(db),
        "storage": settings.storage_backend,
        "appEnv": settings.app_env,
    }


@router.post("/settings/invite-only")
def set_invite_only(payload: InviteOnlyIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    app_settings.set_value(db, app_settings.INVITE_ONLY, "true" if payload.inviteOnly else "false")
    db.commit()
    return {"inviteOnly": payload.inviteOnly}


@router.get("/learned-rules")
def list_learned_rules(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    rules = db.query(LearnedFieldRule).order_by(LearnedFieldRule.updated_at.desc()).all()
    mappings = db.query(LearnedFieldMapping).order_by(LearnedFieldMapping.updated_at.desc()).all()
    return {
        "rules": [
            {
                "id": str(r.id),
                "canonicalKey": r.canonical_key,
                "aliases": r.aliases,
                "dataType": r.data_type,
                "maxLength": r.max_length,
                "regex": r.regex,
                "regexPrompt": r.regex_prompt,
                "active": bool(r.active),
                "useCount": r.use_count or 0,
                "updatedAt": r.updated_at.isoformat() if r.updated_at else None,
            }
            for r in rules
        ],
        "mappings": [
            {
                "id": str(m.id),
                "sourceCanonical": m.source_canonical,
                "sapTable": m.sap_table,
                "sapField": m.sap_field,
                "active": bool(m.active),
                "useCount": m.use_count or 0,
                "updatedAt": m.updated_at.isoformat() if m.updated_at else None,
            }
            for m in mappings
        ],
    }


@router.patch("/learned-rules/{rule_id}")
def patch_learned_rule(
    rule_id: str,
    payload: LearnedRulePatch,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(LearnedFieldRule, rule_id)
    if not row:
        raise HTTPException(404, "Learned rule not found")
    if payload.active is not None:
        row.active = payload.active
    if payload.max_length is not None:
        row.max_length = payload.max_length
    if payload.data_type is not None:
        row.data_type = payload.data_type
    if payload.regex is not None:
        row.regex = payload.regex
    if payload.regex_prompt is not None:
        row.regex_prompt = payload.regex_prompt
    db.commit()
    return {"ok": True}


@router.post("/learned-mappings/{mapping_id}/active")
def set_mapping_active(
    mapping_id: str,
    payload: ActiveIn,
    _: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    row = db.get(LearnedFieldMapping, mapping_id)
    if not row:
        raise HTTPException(404, "Learned mapping not found")
    row.active = payload.isActive
    db.commit()
    return {"ok": True}


@router.get("/llm-spend")
def llm_spend(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    since = datetime.now(timezone.utc) - timedelta(days=30)
    rows = (
        db.query(
            func.date_trunc("day", LlmUsageLog.created_at),
            func.coalesce(func.sum(LlmUsageLog.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageLog.output_tokens), 0),
            func.coalesce(func.sum(LlmUsageLog.estimated_usd), 0),
            func.count(LlmUsageLog.id),
            func.coalesce(func.sum(case_cache_hits()), 0),
        )
        .filter(LlmUsageLog.created_at >= since)
        .group_by(func.date_trunc("day", LlmUsageLog.created_at))
        .order_by(func.date_trunc("day", LlmUsageLog.created_at).desc())
        .all()
    )
    by_user = (
        db.query(
            User.email,
            func.coalesce(func.sum(LlmUsageLog.input_tokens), 0),
            func.coalesce(func.sum(LlmUsageLog.output_tokens), 0),
            func.coalesce(func.sum(LlmUsageLog.estimated_usd), 0),
        )
        .outerjoin(User, User.id == LlmUsageLog.user_id)
        .filter(LlmUsageLog.created_at >= since)
        .group_by(User.email)
        .order_by(func.sum(LlmUsageLog.estimated_usd).desc())
        .limit(20)
        .all()
    )
    cache_rows = db.query(func.count(LlmResponseCache.prompt_hash)).scalar() or 0
    total_calls = sum(int(r[4] or 0) for r in rows)
    cache_hits = sum(int(r[5] or 0) for r in rows)
    return {
        "days": [
            {
                "day": (day.isoformat() if day else None),
                "inputTokens": int(inp or 0),
                "outputTokens": int(out or 0),
                "estimatedUsd": float(usd or 0),
                "calls": int(calls or 0),
                "cacheHits": int(hits or 0),
            }
            for day, inp, out, usd, calls, hits in rows
        ],
        "byUser": [
            {
                "email": email or "unknown",
                "inputTokens": int(inp or 0),
                "outputTokens": int(out or 0),
                "estimatedUsd": float(usd or 0),
            }
            for email, inp, out, usd in by_user
        ],
        "cacheEntries": int(cache_rows),
        "cacheHitRate": round((cache_hits / total_calls) * 100, 1) if total_calls else 0,
        "totalEstimatedUsd": round(sum(float(r[3] or 0) for r in rows), 4),
    }


def case_cache_hits():
    from sqlalchemy import case
    return case((LlmUsageLog.cache_hit.is_(True), 1), else_=0)


@router.get("/jobs")
def list_jobs(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    validations = (
        db.query(ValidationRun)
        .filter(ValidationRun.status.in_(("running", "failed")))
        .order_by(ValidationRun.created_at.desc())
        .limit(50)
        .all()
    )
    mappings = (
        db.query(Mapping)
        .filter(Mapping.status.in_(("processing", "failed")))
        .order_by(Mapping.created_at.desc())
        .limit(50)
        .all()
    )
    comparisons = (
        db.query(ComparisonRun)
        .filter(ComparisonRun.status.in_(("running", "failed")))
        .order_by(ComparisonRun.created_at.desc())
        .limit(50)
        .all()
    )
    return {
        "validations": [
            {
                "id": str(r.id),
                "name": r.name,
                "status": r.status,
                "errorMessage": r.error_message,
                "processedRows": r.processed_rows,
                "totalRows": r.total_rows,
            }
            for r in validations
        ],
        "mappings": [
            {"id": str(r.id), "name": r.mapping_name, "status": r.status}
            for r in mappings
        ],
        "comparisons": [
            {"id": str(r.id), "name": r.name, "status": r.status}
            for r in comparisons
        ],
    }


@router.post("/jobs/validation/{run_id}/fail")
def fail_validation(run_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    run = db.get(ValidationRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    run.status = "failed"
    run.error_message = run.error_message or "Marked failed by admin"
    db.commit()
    return {"ok": True}


@router.post("/jobs/validation/{run_id}/retry")
def retry_validation(run_id: str, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    from services import job_queue
    run = db.get(ValidationRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    run.status = "running"
    run.error_message = None
    db.commit()
    job_queue.submit_validation(run.id)
    return {"ok": True}


@router.get("/health")
def admin_health(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    db_ok = True
    try:
        db.execute(text("SELECT 1"))
    except Exception:
        db_ok = False
    sap = sap_mcp.health(db)
    return {
        "database": "ok" if db_ok else "error",
        "storage": settings.storage_backend,
        "bedrockModel": settings.bedrock_model_id,
        "sap": sap,
        "inviteOnly": app_settings.invite_only(db),
    }


@router.post("/sap/test")
def test_sap(_: User = Depends(require_admin), db: Session = Depends(get_db)):
    return sap_mcp.health(db)


@router.post("/sap/enabled")
def set_sap_enabled(payload: SapToggleIn, _: User = Depends(require_admin), db: Session = Depends(get_db)):
    app_settings.set_value(db, app_settings.SAP_MCP_ENABLED, "true" if payload.enabled else "false")
    db.commit()
    return {"enabled": payload.enabled}
