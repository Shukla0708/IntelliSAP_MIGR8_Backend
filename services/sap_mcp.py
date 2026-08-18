"""Read-only S/4HANA MCP client. Falls back to the local DDIC catalog."""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx
from sqlalchemy.orm import Session

from config import settings
from services import app_settings, sap_ddic

logger = logging.getLogger(__name__)

_LAST = {"ok": False, "at": None, "error": None, "mode": "catalog"}


def health(db: Session | None = None) -> dict:
    enabled = True
    if db is not None:
        enabled = app_settings.sap_mcp_enabled(db)
    if not enabled:
        return {**_LAST, "enabled": False, "mode": "catalog"}
    if not (settings.sap_mcp_url or "").strip():
        _LAST.update({"ok": True, "at": datetime.now(timezone.utc).isoformat(), "error": None, "mode": "catalog"})
        return {**_LAST, "enabled": True, "message": "No SAP MCP URL configured; using local DDIC catalog."}
    try:
        headers = {}
        if settings.sap_mcp_token:
            headers["Authorization"] = f"Bearer {settings.sap_mcp_token}"
        with httpx.Client(timeout=8.0) as client:
            resp = client.get(settings.sap_mcp_url.rstrip("/") + "/health", headers=headers)
            resp.raise_for_status()
        _LAST.update({"ok": True, "at": datetime.now(timezone.utc).isoformat(), "error": None, "mode": "mcp"})
    except Exception:
        logger.warning("SAP MCP health check failed")
        _LAST.update({
            "ok": False,
            "at": datetime.now(timezone.utc).isoformat(),
            "error": "SAP_UNREACHABLE",
            "mode": "catalog",
        })
    return {**_LAST, "enabled": True}


def get_table_fields(table: str, db: Session | None = None) -> dict:
    """Replace mock Fetch from SAP. Local DDIC is the fallback when MCP is down."""
    table_name = (table or "").strip().upper()
    if not table_name:
        return {"table": table_name, "fields": [], "source": "none"}

    if db is None or app_settings.sap_mcp_enabled(db):
        live = _mcp_table_fields(table_name)
        if live is not None:
            return {"table": table_name, "fields": live, "source": "sap"}

    fields = sap_ddic.fields_for_table(table_name) if hasattr(sap_ddic, "fields_for_table") else []
    if not fields:
        fields = _catalog_fields(table_name)
    return {"table": table_name, "fields": fields, "source": "catalog"}


def _mcp_table_fields(table: str) -> list[dict] | None:
    url = (settings.sap_mcp_url or "").strip()
    if not url:
        return None
    headers = {}
    if settings.sap_mcp_token:
        headers["Authorization"] = f"Bearer {settings.sap_mcp_token}"
    try:
        with httpx.Client(timeout=15.0) as client:
            resp = client.post(
                url.rstrip("/") + "/tools/sap_get_table_fields",
                json={"table": table},
                headers=headers,
            )
            resp.raise_for_status()
            data = resp.json()
        fields = data.get("fields") if isinstance(data, dict) else data
        if isinstance(fields, list):
            _LAST.update({"ok": True, "at": datetime.now(timezone.utc).isoformat(), "error": None, "mode": "mcp"})
            return fields
    except Exception:
        logger.warning("sap_get_table_fields failed; using catalog")
        _LAST.update({
            "ok": False,
            "at": datetime.now(timezone.utc).isoformat(),
            "error": "SAP_UNREACHABLE",
            "mode": "catalog",
        })
    return None


def _catalog_fields(table: str) -> list[dict]:
    catalog = []
    getter = getattr(sap_ddic, "iter_fields", None) or getattr(sap_ddic, "all_fields", None)
    if callable(getter):
        for item in getter():
            if str(item.get("table") or item.get("sap_table") or "").upper() == table:
                catalog.append(item)
    return catalog
