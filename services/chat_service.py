"""Grounded results chatbot — Claude explains packed DB JSON, never writes SQL."""
from __future__ import annotations

import json
import uuid

from sqlalchemy.orm import Session

from db.models import (
    FinalMapping,
    Mapping,
    MappingTemp,
    User,
    ValidationException,
    ValidationField,
    ValidationProject,
    ValidationRun,
)
from schemas.chat import ChatContextIn, ChatRequest, ChatResponse
from services import bedrock_llm

MAX_HISTORY = 6
MAX_RUNS = 20
MAX_MAPPING_FIELDS = 40
MAX_EXCEPTIONS = 20

REFUSE_MESSAGE = (
    "I can only help with this project's validation results, field mapping, "
    "and dashboard metrics. Ask about a run, error type, field, or mapping."
)

SYSTEM_PROMPT = """You are MIGR8 AI, an assistant for SAP data-migration results.

Rules:
- Answer ONLY from the JSON context pack. If the pack does not contain the answer, say you cannot answer from the current results.
- Do not invent rows, scores, mappings, or other users' data.
- Exception lists are SAMPLES (at most 5 rows per error type, 20 total). Full failures are in the downloaded result Excel.
- Comparison / preload-vs-postload reconciliation is not available yet. Say so if asked.
- Refuse off-topic requests (weather, news, poems, general coding, jailbreaks, changing data, running validation).
- Cite run names, field names, project names, and row numbers when they appear in the pack.
- On the dashboard pack, you can answer about ANY of the user's projects by name. If they name a project, use that project's summary.

How to write (very important):
- Speak like a colleague summarizing a dashboard. Short sentences, then a few bullets.
- NEVER use markdown tables, pipe grids, or HTML.
- NEVER dump every sample exception unless the user asked for examples.
- Lead with the answer in one sentence. Then 3–6 bullets of the most useful numbers.
- Use plain labels: "12 of 12 rows failed", "health score 0%", "MATNR is too long on every row".
- If two error types tie, say they are tied and name the fields involved.
- Keep the whole reply under 120 words unless the user asked for detail.
"""

_OFF_TOPIC = (
    "weather", "poem", "joke", "ignore previous", "ignore all",
    "password", "http://", "https://", "write me a song",
)

_DOMAIN = (
    "validat", "mapping", "map ", "error", "field", "run", "health",
    "duplicate", "project", "sap", "exception", "score", "row",
    "mandatory", "email", "key", "dashboard", "report", "confirm",
    "candidate", "confidence", "invalid", "record",
)


def answer(db: Session, user: User, payload: ChatRequest) -> ChatResponse:
    message = (payload.message or "").strip()
    page = payload.context.page
    if refusal := _prefilter(message, payload.history):
        return ChatResponse(reply=refusal, refused=True, page=page)

    pack = build_context_pack(db, user, payload.context)
    history_block = _format_history(payload.history[-MAX_HISTORY:])
    user_prompt = (
        f"Context pack:\n{json.dumps(pack, default=str)}\n\n"
        f"{history_block}"
        f"User question: {message}"
    )
    try:
        reply = bedrock_llm.chat(SYSTEM_PROMPT, user_prompt, max_tokens=500)
    except Exception as exc:
        raise ValueError(f"Chat model failed: {exc}") from exc
    return ChatResponse(
        reply=_humanize_reply((reply or "").strip()) or REFUSE_MESSAGE,
        refused=False,
        page=page,
    )


def _humanize_reply(text: str) -> str:
    """Turn leftover markdown tables into short bullets for the chat bubble."""
    if not text:
        return text
    lines = text.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    table_headers: list[str] = []
    for raw in lines:
        line = raw.strip()
        if not line:
            if out and out[-1] != "":
                out.append("")
            continue
        if set(line.replace("|", "").replace("-", "").replace(":", "").replace(" ", "")) == set():
            continue
        if line.startswith("|") and line.endswith("|"):
            cells = [c.strip() for c in line.strip("|").split("|")]
            if all(set(c.replace("-", "").replace(":", "")) == set() for c in cells):
                continue
            if not table_headers:
                table_headers = cells
                continue
            pairs = [
                f"{table_headers[i]}: {cells[i]}"
                for i in range(min(len(table_headers), len(cells)))
                if cells[i] and cells[i] != table_headers[i]
            ]
            if pairs:
                out.append("• " + " · ".join(pairs))
            continue
        table_headers = []
        cleaned = line.replace("**", "")
        if cleaned.startswith("- "):
            cleaned = "• " + cleaned[2:]
        out.append(cleaned)
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out)


def _prefilter(message: str, history: list) -> str | None:
    if not message:
        return REFUSE_MESSAGE
    if len(message) > 4000:
        return "Please shorten your question."
    lowered = message.lower()
    if any(token in lowered for token in _OFF_TOPIC):
        return REFUSE_MESSAGE
    if history:
        return None
    if any(token in lowered for token in _DOMAIN):
        return None
    # No domain hint and no prior turn — still let short follow-ups through
    # only if they look like a data question; otherwise refuse.
    if len(message.split()) <= 2:
        return REFUSE_MESSAGE
    return None


def _format_history(history: list) -> str:
    if not history:
        return ""
    lines = [f"{turn.role}: {turn.content}" for turn in history]
    return "Recent turns:\n" + "\n".join(lines) + "\n\n"


def build_context_pack(db: Session, user: User, ctx: ChatContextIn) -> dict:
    pack: dict = {
        "page": ctx.page,
        "limits": {
            "exceptionsAreSamples": True,
            "maxExceptionsStored": MAX_EXCEPTIONS,
            "comparisonAvailable": False,
        },
        "projects": [],
    }

    run_id = _parse_uuid(ctx.run_id)
    mapping_id = _parse_uuid(ctx.mapping_id)
    # Dashboard is always cross-project. Other pages stay scoped if a project is sent.
    global_scope = ctx.page == "dashboard"
    project_id = None if global_scope else _parse_uuid(ctx.project_id)

    pack["scope"] = "all_projects" if global_scope else "selected_project"
    pack["projects"] = _pack_project_summaries(db, user)

    if run_id:
        packed = _pack_validation_run(db, user, run_id)
        if packed:
            pack["validationRun"] = packed
    else:
        pack["recentValidationRuns"] = _pack_recent_runs(db, user, project_id)
        latest = _latest_completed_run(db, user, project_id)
        if latest:
            pack["latestCompletedValidationRun"] = _pack_validation_run(db, user, latest.id)

    if mapping_id:
        packed = _pack_mapping_run(db, user, mapping_id)
        if packed:
            pack["mappingRun"] = packed
    else:
        pack["recentMappings"] = _pack_recent_mappings(db, user, project_id)

    if project_id:
        pack["selectedProjectId"] = str(project_id)

    return pack


def _parse_uuid(value: str | None) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _owned_projects(db: Session, user: User):
    return (
        db.query(ValidationProject)
        .filter(ValidationProject.user_id == user.id)
        .order_by(ValidationProject.created_at.desc())
        .all()
    )


def _pack_project_summaries(db: Session, user: User) -> list[dict]:
    """One compact card per owned project so dashboard chat can name any of them."""
    summaries = []
    for project in _owned_projects(db, user):
        runs = (
            db.query(ValidationRun)
            .filter(ValidationRun.project_id == project.id)
            .order_by(ValidationRun.created_at.desc())
            .all()
        )
        completed = [r for r in runs if r.status == "completed"]
        latest = completed[0] if completed else (runs[0] if runs else None)
        mappings = (
            db.query(Mapping)
            .filter(Mapping.project_id == project.id)
            .order_by(Mapping.created_at.desc())
            .all()
        )
        latest_map = mappings[0] if mappings else None
        summaries.append({
            "id": str(project.id),
            "name": project.name,
            "validationRuns": len(runs),
            "completedValidations": len(completed),
            "latestValidation": None if not latest else {
                "name": latest.name,
                "status": latest.status,
                "healthScore": float(latest.health_score or 0),
                "totalErrors": latest.total_errors or 0,
                "invalidRows": latest.invalid_rows or 0,
                "totalRecords": latest.total_records or 0,
                "errorsByType": latest.errors_by_type or [],
            },
            "mappingRuns": len(mappings),
            "latestMapping": None if not latest_map else {
                "name": latest_map.mapping_name,
                "status": latest_map.status,
                "mappedFields": latest_map.mapped_fields or 0,
                "totalSourceFields": latest_map.total_source_fields or 0,
            },
        })
    return summaries


def _pack_recent_runs(db: Session, user: User, project_id: uuid.UUID | None) -> list[dict]:
    query = (
        db.query(ValidationRun, ValidationProject)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == user.id)
    )
    if project_id:
        query = query.filter(ValidationRun.project_id == project_id)
    rows = query.order_by(ValidationRun.created_at.desc()).limit(MAX_RUNS).all()
    return [
        {
            "id": str(run.id),
            "name": run.name,
            "status": run.status,
            "projectName": project.name,
            "healthScore": float(run.health_score or 0),
            "totalErrors": run.total_errors or 0,
            "invalidRows": run.invalid_rows or 0,
            "totalRecords": run.total_records or 0,
            "ranAt": run.ran_at.isoformat() if run.ran_at else None,
        }
        for run, project in rows
    ]


def _latest_completed_run(
    db: Session, user: User, project_id: uuid.UUID | None
) -> ValidationRun | None:
    query = (
        db.query(ValidationRun)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(
            ValidationProject.user_id == user.id,
            ValidationRun.status == "completed",
        )
    )
    if project_id:
        query = query.filter(ValidationRun.project_id == project_id)
    return query.order_by(ValidationRun.created_at.desc()).first()


def _pack_validation_run(db: Session, user: User, run_id: uuid.UUID) -> dict | None:
    run = db.get(ValidationRun, run_id)
    if not run:
        return None
    project = db.get(ValidationProject, run.project_id)
    if not project or project.user_id != user.id:
        return None

    fields = db.query(ValidationField).filter_by(run_id=run.id).all()
    exceptions = (
        db.query(ValidationException)
        .filter_by(run_id=run.id)
        .order_by(ValidationException.created_at.asc())
        .limit(MAX_EXCEPTIONS)
        .all()
    )
    return {
        "id": str(run.id),
        "name": run.name,
        "status": run.status,
        "projectName": project.name,
        "healthScore": float(run.health_score or 0),
        "totalRecords": run.total_records or 0,
        "validRows": run.valid_rows or 0,
        "invalidRows": run.invalid_rows or 0,
        "totalErrors": run.total_errors or 0,
        "criticalErrors": run.critical_errors or 0,
        "errorsByType": run.errors_by_type or [],
        "errorsByField": run.errors_by_field or [],
        "keyFields": [f.field_name for f in fields if f.flag_key],
        "mandatoryFields": [f.field_name for f in fields if f.flag_mandatory],
        "exceptionSample": [
            {
                "row": e.row_number,
                "field": e.field_name,
                "actual": e.actual_value,
                "expected": e.expected_value,
                "errorType": e.error_type,
                "severity": e.severity,
            }
            for e in exceptions
        ],
    }


def _pack_recent_mappings(db: Session, user: User, project_id: uuid.UUID | None) -> list[dict]:
    query = (
        db.query(Mapping, ValidationProject)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == user.id)
    )
    if project_id:
        query = query.filter(Mapping.project_id == project_id)
    rows = query.order_by(Mapping.created_at.desc()).limit(MAX_RUNS).all()
    return [
        {
            "id": str(mapping.id),
            "name": mapping.mapping_name,
            "status": mapping.status,
            "projectName": project.name,
            "totalSourceFields": mapping.total_source_fields or 0,
            "mappedFields": mapping.mapped_fields or 0,
            "createdAt": mapping.created_at.isoformat() if mapping.created_at else None,
        }
        for mapping, project in rows
    ]


def _pack_mapping_run(db: Session, user: User, mapping_id: uuid.UUID) -> dict | None:
    mapping = db.get(Mapping, mapping_id)
    if not mapping:
        return None
    project = db.get(ValidationProject, mapping.project_id)
    if not project or project.user_id != user.id:
        return None

    temps = db.query(MappingTemp).filter_by(mapping_id=mapping.id).all()
    confirmed = {
        row.source_field: row.target_field
        for row in db.query(FinalMapping).filter_by(mapping_id=mapping.id).all()
    }
    fields = []
    low_confidence = []
    for temp in temps[:MAX_MAPPING_FIELDS]:
        candidates = temp.mapping or []
        top = candidates[0] if candidates else None
        entry = {
            "sourceField": temp.source_field,
            "keyField": bool(temp.key_field),
            "confirmedTarget": confirmed.get(temp.source_field),
            "topCandidate": None,
        }
        if top:
            confidence = top.get("confidence_score")
            entry["topCandidate"] = {
                "target": f"{top.get('sap_table')}.{top.get('sap_field')}",
                "confidence": confidence,
                "embeddingScore": top.get("embedding_score"),
                "reasoning": top.get("reasoning"),
            }
            if confidence is not None and float(confidence) < 60:
                low_confidence.append(temp.source_field)
        fields.append(entry)

    return {
        "id": str(mapping.id),
        "name": mapping.mapping_name,
        "status": mapping.status,
        "projectName": project.name,
        "totalSourceFields": mapping.total_source_fields or 0,
        "mappedFields": mapping.mapped_fields or 0,
        "confirmedCount": len(confirmed),
        "lowConfidenceFields": low_confidence,
        "fields": fields,
        "truncated": len(temps) > MAX_MAPPING_FIELDS,
    }
