"""Allow-listed chat actions: explain, suggest, summarize — never free-form SQL."""
from __future__ import annotations

import logging
import re
import uuid
from pathlib import Path

from sqlalchemy.orm import Session

from db.models import (
    ComparisonRun,
    FinalMapping,
    LearnedFieldRule,
    Mapping,
    User,
    ValidationField,
    ValidationProject,
    ValidationRun,
)
from schemas.chat import ChatContextIn
from services import (
    entity_resolution,
    file_stream,
    learned_rules,
    rule_suggester,
    rule_templates,
    s3_service,
)

logger = logging.getLogger(__name__)

MAX_SAMPLE_ROWS = 200
MAX_SAMPLES = 20

ACTIONS = (
    "suggest_rules",
    "explain_failures",
    "summarize_comparison",
    "generate_load_layout",
    "find_duplicates",
)

_FIELD_TOKEN = re.compile(r"\b([A-Z][A-Z0-9_]{2,})\b")


def detect(message: str) -> str | None:
    text = (message or "").lower()
    if any(token in text for token in ("lsmw", "cockpit", "load layout", "load template")):
        return "generate_load_layout"
    if any(token in text for token in ("duplicate customer", "find duplicate", "near duplicate", "entity resol")):
        return "find_duplicates"
    if any(token in text for token in ("suggest rule", "apply rules", "generate rules", "ai rules")):
        return "suggest_rules"
    if (
        any(token in text for token in ("summarize", "summary", "sum up"))
        and any(token in text for token in ("comparison", "preload", "postload", "reconcil"))
    ):
        return "summarize_comparison"
    if any(token in text for token in ("explain", "why did", "failures", "failing", "why is")):
        return "explain_failures"
    return None


def extract_field_hint(message: str) -> str | None:
    matches = _FIELD_TOKEN.findall(message or "")
    skip = {"SAP", "LSMW", "CSV", "XML", "THE", "AND", "FOR", "WHY"}
    for token in matches:
        if token not in skip:
            return token
    return None


def execute(
    db: Session,
    user: User,
    ctx: ChatContextIn,
    action: str,
    message: str,
) -> dict:
    if action == "suggest_rules":
        return _suggest_rules(db, user, ctx)
    if action == "find_duplicates":
        return _find_duplicates(db, user, ctx)
    if action == "generate_load_layout":
        return _load_layout(db, user, ctx)
    if action == "summarize_comparison":
        return _summarize_comparison(db, user, ctx)
    if action == "explain_failures":
        return {
            "type": "explain_failures",
            "status": "ok",
            "fieldHint": extract_field_hint(message),
            "href": _validation_href(ctx.run_id),
        }
    return {"type": action, "status": "skipped", "detail": "Unknown action"}


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _suggest_rules(db: Session, user: User, ctx: ChatContextIn) -> dict:
    run = _draft_run(db, user, ctx)
    if not run:
        return {
            "type": "suggest_rules",
            "status": "skipped",
            "detail": "No draft validation run with a source file was found.",
        }
    fields = (
        db.query(ValidationField)
        .filter_by(run_id=run.id)
        .order_by(ValidationField.column_index)
        .all()
    )
    if not fields:
        return {
            "type": "suggest_rules",
            "status": "skipped",
            "detail": f"Draft '{run.name}' has no fields yet. Upload a source file first.",
            "href": f"/validation/{run.id}",
        }

    samples_by_field = _sample_source(run)
    payload = [
        {"field_name": f.field_name, "samples": samples_by_field.get(f.field_name, [])}
        for f in fields
        if f.rule_source != "user"
    ]
    if not payload:
        return {
            "type": "suggest_rules",
            "status": "skipped",
            "detail": "Every field already has a user-edited rule. Nothing to suggest.",
            "href": f"/validation/{run.id}",
        }

    templates = rule_templates.load_templates(db)
    learned_map = {
        row.canonical_key: learned_rules.rule_to_template(row)
        for row in db.query(LearnedFieldRule).filter(LearnedFieldRule.active.is_(True)).all()
    }
    result = rule_suggester.suggest_rules(payload, templates, learned=learned_map)
    by_name = {s["field_name"]: s for s in result.get("suggestions") or []}
    applied = 0
    for field in fields:
        suggestion = by_name.get(field.field_name)
        if not suggestion or field.rule_source == "user":
            continue
        field.flag_mandatory = suggestion.get("flag_mandatory", False)
        field.flag_null = suggestion.get("flag_null", False)
        field.flag_email = suggestion.get("flag_email", False)
        field.flag_mobile = suggestion.get("flag_mobile", False)
        field.flag_date = suggestion.get("flag_date", False)
        field.flag_special_chars = suggestion.get("flag_special_chars", False)
        field.case_format = suggestion.get("case_format")
        field.data_type = suggestion.get("data_type") or "string"
        field.max_length = suggestion.get("max_length")
        field.decimal_length = suggestion.get("decimal_length")
        field.regex = suggestion.get("regex")
        field.regex_prompt = suggestion.get("regex_prompt")
        field.rule_source = suggestion.get("rule_source") or "ai"
        applied += 1
    if run.status in ("draft", "failed"):
        run.status = "rules_configured"
    db.commit()
    return {
        "type": "suggest_rules",
        "status": "ok",
        "applied": applied,
        "runId": str(run.id),
        "runName": run.name,
        "href": f"/validation/{run.id}",
        "reply": (
            f"I applied AI rule suggestions to {applied} field"
            f"{'s' if applied != 1 else ''} on draft '{run.name}'. "
            "Open the run to review them before you execute."
        ),
    }


def _find_duplicates(db: Session, user: User, ctx: ChatContextIn) -> dict:
    run = _completed_validation(db, user, ctx)
    if not run:
        return {
            "type": "find_duplicates",
            "status": "skipped",
            "detail": "No completed validation run to scan for duplicates.",
        }
    payload = run.duplicate_groups
    if not payload and run.source_s3_key:
        payload = _scan_and_store(db, run)
    groups = (payload or {}).get("groups") or []
    count = (payload or {}).get("groupCount") or 0
    if payload and payload.get("skippedReason"):
        reply = payload["skippedReason"]
    elif count:
        names = []
        for group in groups[:5]:
            labels = [r.get("name") or f"row {r.get('row')}" for r in group.get("rows") or []]
            names.append(" / ".join(labels[:2]))
        reply = (
            f"These {count} customer groups look like duplicates before a KNA1 load: "
            + "; ".join(names)
            + "."
        )
    else:
        reply = f"No likely duplicates in '{run.name}' on name, city, or tax id."
    return {
        "type": "find_duplicates",
        "status": "ok",
        "runId": str(run.id),
        "groupCount": count,
        "href": f"/validation_result/{run.id}",
        "reply": reply,
    }


def _load_layout(db: Session, user: User, ctx: ChatContextIn) -> dict:
    mapping = _confirmed_mapping(db, user, ctx)
    if not mapping:
        return {
            "type": "generate_load_layout",
            "status": "skipped",
            "detail": "No approved field mapping to build a load layout from.",
        }
    confirmed = db.query(FinalMapping).filter_by(mapping_id=mapping.id).count()
    return {
        "type": "generate_load_layout",
        "status": "ok",
        "mappingId": str(mapping.id),
        "mappingName": mapping.mapping_name,
        "confirmedFields": confirmed,
        "href": f"/field-mapping/{mapping.id}",
        "reply": (
            f"Load layout is ready for '{mapping.mapping_name}' "
            f"({confirmed} confirmed fields). Download Migration Cockpit CSV or LSMW XML "
            "from the mapping workspace."
        ),
    }


def _summarize_comparison(db: Session, user: User, ctx: ChatContextIn) -> dict:
    run = _completed_comparison(db, user, ctx)
    if not run:
        return {
            "type": "summarize_comparison",
            "status": "skipped",
            "detail": "No completed comparison run to summarize.",
        }
    return {
        "type": "summarize_comparison",
        "status": "ok",
        "comparisonId": str(run.id),
        "href": f"/compare/{run.id}",
    }


def _draft_run(db: Session, user: User, ctx: ChatContextIn) -> ValidationRun | None:
    run_id = _parse_uuid(ctx.run_id)
    if run_id:
        run = db.get(ValidationRun, run_id)
        if run and _owns_project(db, user, run.project_id) and run.source_s3_key:
            return run
    project_id = _parse_uuid(ctx.project_id)
    query = (
        db.query(ValidationRun)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(
            ValidationProject.user_id == user.id,
            ValidationRun.source_s3_key.isnot(None),
            ValidationRun.status.in_(("draft", "rules_configured")),
        )
    )
    if project_id:
        query = query.filter(ValidationRun.project_id == project_id)
    return query.order_by(ValidationRun.created_at.desc()).first()


def _completed_validation(db: Session, user: User, ctx: ChatContextIn) -> ValidationRun | None:
    run_id = _parse_uuid(ctx.run_id)
    if run_id:
        run = db.get(ValidationRun, run_id)
        if run and _owns_project(db, user, run.project_id) and run.status == "completed":
            return run
    project_id = _parse_uuid(ctx.project_id)
    query = (
        db.query(ValidationRun)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == user.id, ValidationRun.status == "completed")
    )
    if project_id:
        query = query.filter(ValidationRun.project_id == project_id)
    return query.order_by(ValidationRun.completed_at.desc().nullslast(), ValidationRun.created_at.desc()).first()


def _completed_comparison(db: Session, user: User, ctx: ChatContextIn) -> ComparisonRun | None:
    run_id = _parse_uuid(ctx.comparison_id)
    if run_id:
        run = db.get(ComparisonRun, run_id)
        if run and _owns_project(db, user, run.project_id) and run.status == "completed":
            return run
    project_id = _parse_uuid(ctx.project_id)
    query = (
        db.query(ComparisonRun)
        .join(ValidationProject, ComparisonRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == user.id, ComparisonRun.status == "completed")
    )
    if project_id:
        query = query.filter(ComparisonRun.project_id == project_id)
    return query.order_by(ComparisonRun.completed_at.desc().nullslast(), ComparisonRun.created_at.desc()).first()


def _confirmed_mapping(db: Session, user: User, ctx: ChatContextIn) -> Mapping | None:
    mapping_id = _parse_uuid(ctx.mapping_id)
    if mapping_id:
        mapping = db.get(Mapping, mapping_id)
        if mapping and _owns_project(db, user, mapping.project_id):
            return mapping
    project_id = _parse_uuid(ctx.project_id)
    query = (
        db.query(Mapping)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .join(FinalMapping, FinalMapping.mapping_id == Mapping.id)
        .filter(ValidationProject.user_id == user.id)
    )
    if project_id:
        query = query.filter(Mapping.project_id == project_id)
    return query.order_by(Mapping.created_at.desc()).first()


def _owns_project(db: Session, user: User, project_id) -> bool:
    project = db.get(ValidationProject, project_id)
    return bool(project and project.user_id == user.id)


def _validation_href(run_id: str | None) -> str | None:
    return f"/validation_result/{run_id}" if run_id else None


def _sample_source(run: ValidationRun) -> dict[str, list[str]]:
    if not run.source_s3_key:
        return {}
    suffix = Path(run.source_filename or "source.xlsx").suffix or ".xlsx"
    tmp = s3_service.download_to_temp(run.source_s3_key, suffix=suffix)
    try:
        headers = file_stream.extract_headers_from_path(tmp, run.source_filename or "source.xlsx")
        samples: dict[str, list[str]] = {h: [] for h in headers}
        for row_number, values in file_stream.iter_data_rows(tmp, run.source_filename or "source.xlsx"):
            if row_number > MAX_SAMPLE_ROWS + 1:
                break
            done = True
            for idx, header in enumerate(headers):
                bucket = samples[header]
                if len(bucket) >= MAX_SAMPLES:
                    continue
                done = False
                if idx < len(values) and values[idx] not in (None, ""):
                    text = str(values[idx]).strip()
                    if text and text not in bucket:
                        bucket.append(text)
            if done:
                break
        return samples
    finally:
        tmp.unlink(missing_ok=True)


def _scan_and_store(db: Session, run: ValidationRun) -> dict:
    suffix = Path(run.source_filename or "source.xlsx").suffix or ".xlsx"
    tmp = s3_service.download_to_temp(run.source_s3_key, suffix=suffix)
    try:
        payload = entity_resolution.scan_file(tmp, run.source_filename or "source.xlsx")
    finally:
        tmp.unlink(missing_ok=True)
    run.duplicate_groups = payload
    db.commit()
    return payload
