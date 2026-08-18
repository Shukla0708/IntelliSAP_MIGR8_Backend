"""Instance-wide key/value settings (invite-only signup, SAP MCP toggle)."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import AppSetting

INVITE_ONLY = "invite_only"
SAP_MCP_ENABLED = "sap_mcp_enabled"


def get_value(db: Session, key: str, default: str = "") -> str:
    row = db.get(AppSetting, key)
    return row.value if row else default


def set_value(db: Session, key: str, value: str) -> None:
    row = db.get(AppSetting, key)
    if row is None:
        db.add(AppSetting(key=key, value=value, updated_at=datetime.now(timezone.utc)))
    else:
        row.value = value
        row.updated_at = datetime.now(timezone.utc)


def invite_only(db: Session) -> bool:
    return get_value(db, INVITE_ONLY, "false").lower() in ("1", "true", "yes")


def sap_mcp_enabled(db: Session) -> bool:
    return get_value(db, SAP_MCP_ENABLED, "true").lower() in ("1", "true", "yes")
