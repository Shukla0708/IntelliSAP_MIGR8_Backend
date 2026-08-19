"""Migration Cockpit / LSMW load layout from a confirmed field mapping."""
from __future__ import annotations

import csv
import io
import json
import logging
from xml.sax.saxutils import escape

from config import settings
from services import bedrock_llm

logger = logging.getLogger(__name__)

_FILL_SYSTEM = (
    "You write one-sentence 'how to fill' notes for an SAP Migration Cockpit / "
    "LSMW load file. Return ONLY JSON: "
    '{"notes":[{"source_field":"...","note":"..."}]}. '
    "Each note is <= 18 words. Mention the SAP field. No markdown."
)


def build_layout(
    mapping_name: str,
    fields: list[dict],
    *,
    fmt: str = "csv",
    with_llm_notes: bool = True,
) -> tuple[bytes, str, str]:
    """Return (body, media_type, filename).

    Each field dict: source_field, target_field, is_key, description, datatype.
    """
    notes = _fill_notes(fields, with_llm_notes=with_llm_notes)
    rows = []
    for field in fields:
        table, sap_field = _split_target(field.get("target_field") or "")
        rows.append({
            "sap_table": table,
            "sap_field": sap_field,
            "description": field.get("description") or "",
            "source_field": field.get("source_field") or "",
            "is_key": "Y" if field.get("is_key") else "N",
            "datatype": field.get("datatype") or "",
            "fill_note": notes.get(field.get("source_field") or "", _fallback_note(field)),
        })

    safe_name = _safe_filename(mapping_name)
    if fmt == "xml":
        return (
            _to_xml(mapping_name, rows),
            "application/xml",
            f"{safe_name}_lsmw.xml",
        )
    return (
        _to_csv(rows),
        "text/csv; charset=utf-8",
        f"{safe_name}_cockpit.csv",
    )


def _fill_notes(fields: list[dict], *, with_llm_notes: bool) -> dict[str, str]:
    fallback = {f.get("source_field") or "": _fallback_note(f) for f in fields}
    if not with_llm_notes or not fields:
        return fallback
    payload = [
        {
            "source_field": f.get("source_field"),
            "target_field": f.get("target_field"),
            "description": (f.get("description") or "")[:80],
            "is_key": bool(f.get("is_key")),
        }
        for f in fields[:80]
    ]
    try:
        raw = bedrock_llm.chat(
            _FILL_SYSTEM,
            json.dumps({"fields": payload}),
            max_tokens=1200,
            model_id=settings.bedrock_haiku_model_id,
            purpose="load_layout",
            use_cache=True,
        )
        parsed = json.loads(bedrock_llm.strip_markdown_fences(raw or ""))
        for item in parsed.get("notes") or []:
            source = item.get("source_field")
            note = (item.get("note") or "").strip()
            if source and note:
                fallback[source] = note[:240]
    except Exception:
        logger.info("load-layout LLM notes unavailable; using templates")
    return fallback


def _fallback_note(field: dict) -> str:
    target = field.get("target_field") or "the SAP field"
    source = field.get("source_field") or "the source column"
    if field.get("is_key"):
        return f"Load {source} into key field {target}; keep values unique."
    desc = field.get("description") or ""
    if desc:
        return f"Map {source} to {target} ({desc})."
    return f"Map {source} to {target}."


def _to_csv(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    writer = csv.DictWriter(
        buf,
        fieldnames=[
            "SAP_TABLE",
            "SAP_FIELD",
            "DESCRIPTION",
            "SOURCE_FIELD",
            "IS_KEY",
            "DATATYPE",
            "FILL_NOTE",
        ],
    )
    writer.writeheader()
    for row in rows:
        writer.writerow({
            "SAP_TABLE": row["sap_table"],
            "SAP_FIELD": row["sap_field"],
            "DESCRIPTION": row["description"],
            "SOURCE_FIELD": row["source_field"],
            "IS_KEY": row["is_key"],
            "DATATYPE": row["datatype"],
            "FILL_NOTE": row["fill_note"],
        })
    return buf.getvalue().encode("utf-8-sig")


def _to_xml(mapping_name: str, rows: list[dict]) -> bytes:
    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<MigrationCockpitLayout object="{escape(mapping_name)}" generatedBy="MIGR8">',
    ]
    for row in rows:
        parts.append(
            "  <Field"
            f' sapTable="{escape(row["sap_table"])}"'
            f' sapField="{escape(row["sap_field"])}"'
            f' sourceField="{escape(row["source_field"])}"'
            f' key="{escape(row["is_key"])}"'
            f' datatype="{escape(row["datatype"])}"'
            f' description="{escape(row["description"])}">'
        )
        parts.append(f"    <FillNote>{escape(row['fill_note'])}</FillNote>")
        parts.append("  </Field>")
    parts.append("</MigrationCockpitLayout>")
    return "\n".join(parts).encode("utf-8")


def _split_target(target_field: str) -> tuple[str, str]:
    if "." in target_field:
        table, field = target_field.split(".", 1)
        return table, field
    return "", target_field


def _safe_filename(name: str) -> str:
    cleaned = "".join(ch if ch.isalnum() or ch in "-_ " else "_" for ch in (name or "mapping"))
    return (cleaned.strip().replace(" ", "_") or "mapping")[:60]
