"""Cross-user learned validation rules and field mappings (Postgres only)."""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy.orm import Session

from db.models import LearnedFieldMapping, LearnedFieldRule, User, ValidationField
from services.rule_templates import SEED_TEMPLATES

logger = logging.getLogger(__name__)

LEARNED_SCORE = 0.99


def _norm_name(name: str) -> str:
    text = re.sub(r"([a-z])([A-Z])", r"\1 \2", name or "")
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _alias_index(templates: list[dict[str, Any]] | None = None) -> dict[str, str]:
    catalog = templates if templates is not None else SEED_TEMPLATES
    index: dict[str, str] = {}
    for tmpl in catalog:
        canonical = _norm_name(str(tmpl.get("name") or "")).replace(" ", "")
        if len(canonical) < 2:
            continue
        keys = [_norm_name(str(tmpl.get("name") or ""))]
        for part in str(tmpl.get("aliases") or "").split(","):
            keys.append(_norm_name(part))
        for key in keys:
            if len(key) < 2:
                continue
            index.setdefault(key, canonical)
            compact = key.replace(" ", "")
            if compact:
                index.setdefault(compact, canonical)
    return index


def canonical_key(field_name: str, templates: list[dict[str, Any]] | None = None) -> str:
    index = _alias_index(templates)
    norm = _norm_name(field_name)
    compact = norm.replace(" ", "")
    return index.get(norm) or index.get(compact) or compact or _norm_name(field_name)


def rule_to_template(row: LearnedFieldRule) -> dict[str, Any]:
    aliases = row.aliases or ""
    extra = [a.strip() for a in aliases.split(",") if a.strip()]
    if row.canonical_key not in extra:
        extra.insert(0, row.canonical_key)
    return {
        "name": row.canonical_key,
        "aliases": ", ".join(extra),
        "flag_mandatory": bool(row.flag_mandatory),
        "flag_null": bool(row.flag_null),
        "flag_email": bool(row.flag_email),
        "flag_mobile": bool(row.flag_mobile),
        "flag_date": bool(row.flag_date),
        "flag_special_chars": bool(row.flag_special_chars),
        "case_format": row.case_format,
        "data_type": row.data_type or "string",
        "max_length": row.max_length,
        "decimal_length": row.decimal_length,
        "regex_prompt": row.regex_prompt,
        "regex": row.regex,
        "priority": 0,
        "active": bool(row.active),
        "learned": True,
    }


def samples_fit(template: dict[str, Any], samples: list[str]) -> bool:
    if not samples:
        return True
    max_length = template.get("max_length")
    data_type = (template.get("data_type") or "string").lower()
    regex = template.get("regex")
    compiled = None
    if regex:
        try:
            compiled = re.compile(regex)
        except re.error:
            compiled = None
    hits = 0
    for sample in samples:
        text = str(sample).strip()
        if not text:
            continue
        if max_length and len(text) > int(max_length) * 2:
            return False
        if data_type in ("char", "numc") and max_length and len(text) > int(max_length) + 2:
            return False
        if compiled and not compiled.fullmatch(text):
            continue
        hits += 1
    if compiled:
        return hits / max(len(samples), 1) >= 0.6
    return True


def lookup_rule(db: Session, field_name: str, templates: list[dict[str, Any]] | None = None) -> LearnedFieldRule | None:
    key = canonical_key(field_name, templates)
    if not key:
        return None
    return (
        db.query(LearnedFieldRule)
        .filter(LearnedFieldRule.canonical_key == key, LearnedFieldRule.active.is_(True))
        .first()
    )


def lookup_mapping(db: Session, source_field: str) -> LearnedFieldMapping | None:
    key = canonical_key(source_field)
    if not key:
        return None
    return (
        db.query(LearnedFieldMapping)
        .filter(
            LearnedFieldMapping.source_canonical == key,
            LearnedFieldMapping.active.is_(True),
        )
        .first()
    )


def upsert_rule_from_field(db: Session, field: ValidationField, user: User) -> None:
    if (field.rule_source or "") != "user":
        return
    key = canonical_key(field.field_name)
    if not key:
        return
    if field.regex and _looks_like_pii(field.regex):
        logger.info("skipping learned rule for %s: regex looks like sample PII", key)
        return
    row = db.query(LearnedFieldRule).filter(LearnedFieldRule.canonical_key == key).first()
    now = datetime.now(timezone.utc)
    aliases = field.field_name
    if row is None:
        row = LearnedFieldRule(canonical_key=key, aliases=aliases, use_count=0)
        db.add(row)
    else:
        existing = {part.strip() for part in (row.aliases or "").split(",") if part.strip()}
        existing.add(field.field_name)
        row.aliases = ", ".join(sorted(existing))
    row.flag_mandatory = bool(field.flag_mandatory)
    row.flag_null = bool(field.flag_null)
    row.flag_email = bool(field.flag_email)
    row.flag_mobile = bool(field.flag_mobile)
    row.flag_date = bool(field.flag_date)
    row.flag_special_chars = bool(field.flag_special_chars)
    row.case_format = field.case_format
    row.data_type = field.data_type or "string"
    row.max_length = field.max_length
    row.decimal_length = field.decimal_length
    row.regex = field.regex
    row.regex_prompt = field.regex_prompt
    row.updated_by = user.id
    row.updated_at = now
    row.active = True


def bump_rule_use(db: Session, canonical: str) -> None:
    row = db.query(LearnedFieldRule).filter(LearnedFieldRule.canonical_key == canonical).first()
    if row:
        row.use_count = int(row.use_count or 0) + 1


def upsert_mapping(
    db: Session,
    source_field: str,
    sap_table: str,
    sap_field: str,
    user_id: UUID | None,
) -> None:
    key = canonical_key(source_field)
    if not key or not sap_field:
        return
    row = db.query(LearnedFieldMapping).filter(LearnedFieldMapping.source_canonical == key).first()
    now = datetime.now(timezone.utc)
    if row is None:
        row = LearnedFieldMapping(source_canonical=key, use_count=0)
        db.add(row)
    row.sap_table = sap_table
    row.sap_field = sap_field
    row.updated_by = user_id
    row.updated_at = now
    row.active = True


def _looks_like_pii(regex: str) -> bool:
    text = regex or ""
    if "@" in text or re.search(r"\d{8,}", text):
        return True
    return False
