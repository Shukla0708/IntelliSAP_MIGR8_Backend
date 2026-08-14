import logging
import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User, ValidationRun, ValidationField, ValidationException, ValidationProject
from auth import get_current_user
from services import s3_service, regex_generator, file_stream, job_queue, rule_suggester, rule_templates
from schemas import (
    CreateRunRequest,
    FieldRuleIn,
    RegexGenerateRequest,
    RegexGenerateResponse,
    RunDetailOut,
    RunFieldOut,
    SuggestRulesRequest,
    SuggestRulesResponse,
)

router = APIRouter(prefix="/api/runs", tags=["validation"])
logger = logging.getLogger(__name__)


def _get_owned_run(run_id: uuid.UUID, db: Session, current_user: User) -> ValidationRun:
    run = db.get(ValidationRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    project = db.get(ValidationProject, run.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Run not found")
    return run


_VALID_STATUSES = ("draft", "rules_configured", "running", "completed", "failed")


def _list_status(status: str | None) -> str:
    if status in _VALID_STATUSES:
        return status
    return "draft"


@router.get("/")
def list_runs(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List validation runs across all projects owned by the current user."""
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    query = (
        db.query(ValidationRun, ValidationProject)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
    )
    if project_id is not None:
        query = query.filter(ValidationRun.project_id == project_id)

    rows = (
        query.order_by(ValidationRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    return [
        {
            "id": str(run.id),
            "name": run.name,
            "records": f"{run.total_records} records",
            "ranAt": run.ran_at.isoformat() if run.ran_at else None,
            "status": _list_status(run.status),
            "errors": run.total_errors or 0,
            "project_id": str(project.id),
            "project_name": project.name,
        }
        for run, project in rows
    ]


@router.post("/")
def create_run(
    project_id: uuid.UUID,
    payload: CreateRunRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(ValidationProject, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Project not found")

    run = ValidationRun(
        project_id=project_id,
        name=payload.name,
        created_by=current_user.id,
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="A validation run with this name already exists in this project",
        )
    db.refresh(run)
    return {"run_id": str(run.id)}


@router.get("/{run_id}", response_model=RunDetailOut)
def get_run(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    field_rows = (
        db.query(ValidationField)
        .filter_by(run_id=run_id)
        .order_by(ValidationField.column_index)
        .all()
    )
    return RunDetailOut(
        id=str(run.id),
        project_id=str(run.project_id),
        name=run.name,
        status=run.status or "draft",
        source_filename=run.source_filename,
        has_source_file=bool(run.source_s3_key),
        processed_rows=run.processed_rows or 0,
        total_rows=run.total_rows or 0,
        error_message=run.error_message,
        has_result_file=bool(run.result_s3_key),
        fields=[
            RunFieldOut(
                field_name=f.field_name,
                flag_key=f.flag_key or False,
                flag_mandatory=f.flag_mandatory or False,
                flag_null=f.flag_null or False,
                flag_email=f.flag_email or False,
                flag_mobile=f.flag_mobile or False,
                flag_date=f.flag_date or False,
                flag_special_chars=f.flag_special_chars or False,
                case_format=f.case_format,
                data_type=f.data_type or "string",
                max_length=f.max_length,
                decimal_length=f.decimal_length,
                regex=f.regex,
                regex_prompt=f.regex_prompt,
                rule_source=f.rule_source or "default",
            )
            for f in field_rows
        ],
    )


@router.post("/{run_id}/upload")
async def upload_source(run_id: uuid.UUID, file: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)
    filename = file.filename or "source.xlsx"
    try:
        file_stream.sniff_kind(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))

    key = f"validations/{run_id}/source/{filename}"
    await file.seek(0)
    s3_service.upload_fileobj(
        key, file.file, file.content_type or "application/octet-stream",
    )

    stored = s3_service.local_path_if_exists(key)
    if stored:
        fields = file_stream.extract_headers_from_path(stored, filename)
    else:
        tmp = s3_service.download_to_temp(key, suffix="." + filename.rsplit(".", 1)[-1])
        try:
            fields = file_stream.extract_headers_from_path(tmp, filename)
        finally:
            tmp.unlink(missing_ok=True)

    if not fields:
        raise HTTPException(422, "No column headers found in the first row.")

    db.query(ValidationField).filter(ValidationField.run_id == run_id).delete()
    for idx, name in enumerate(fields):
        db.add(ValidationField(run_id=run_id, field_name=name, column_index=idx))

    run.source_filename = filename
    run.source_s3_key = key
    run.status = "draft"
    db.commit()

    return {"fields": fields}


@router.put("/{run_id}/rules")
def save_rules(run_id: uuid.UUID, payload: list[FieldRuleIn], db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    _get_owned_run(run_id, db, current_user)

    for f in payload:
        row = db.query(ValidationField).filter_by(run_id=run_id, field_name=f.field_name).first()
        if not row:
            continue
        row.flag_key = f.flag_key
        row.flag_mandatory = f.flag_mandatory
        row.flag_null = f.flag_null
        row.flag_email = f.flag_email
        row.flag_mobile = f.flag_mobile
        row.flag_date = f.flag_date
        row.flag_special_chars = f.flag_special_chars
        row.case_format = f.case_format
        row.data_type = f.data_type
        row.max_length = f.max_length
        row.decimal_length = f.decimal_length
        row.regex_prompt = f.regex_prompt
        row.rule_source = f.rule_source or "default"
        # If the user wrote a plain-English rule, always ask Bedrock for the regex
        # so Rule 5 stays LLM-driven even if they didn't click Generate in the UI.
        if f.regex_prompt and f.regex_prompt.strip():
            try:
                row.regex = regex_generator.generate_regex(f.field_name, f.regex_prompt)
            except Exception:
                row.regex = f.regex  # fall back to any pattern the UI already has
        else:
            row.regex = f.regex

    db.query(ValidationRun).filter_by(id=run_id).update({"status": "rules_configured"})
    db.commit()
    return {"ok": True}


@router.post("/suggest-rules", response_model=SuggestRulesResponse)
def suggest_rules_route(
    payload: SuggestRulesRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return AI/heuristic rule suggestions. Does not write validation_fields."""
    if not payload.fields:
        raise HTTPException(400, "No fields provided")
    if len(payload.fields) > 500:
        raise HTTPException(400, "Too many fields (max 500)")

    templates = rule_templates.load_templates(db)
    result = rule_suggester.suggest_rules(
        [{"field_name": f.field_name, "samples": f.samples} for f in payload.fields],
        templates,
    )
    return SuggestRulesResponse(
        suggestions=result["suggestions"],
        warning=result.get("warning"),
    )


@router.post("/generate-regex", response_model=RegexGenerateResponse)
def generate_regex_route(payload: RegexGenerateRequest, current_user: User = Depends(get_current_user)):
    try:
        regex = regex_generator.generate_regex(payload.field_name, payload.prompt)
        return RegexGenerateResponse(regex=regex)
    except Exception as exc:
        logger.exception(
            "generate-regex failed for field=%r prompt=%r",
            payload.field_name,
            payload.prompt,
        )
        detail = str(exc).strip() or "Could not generate a valid rule from that prompt."
        raise HTTPException(
            422,
            detail={
                "message": "Could not generate a valid rule from that prompt. Try rephrasing it.",
                "reason": detail,
            },
        )


@router.post("/{run_id}/execute")
def execute_run(run_id: uuid.UUID, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)
    if not run.source_s3_key:
        raise HTTPException(400, "No source file uploaded for this run")
    if run.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "This run is already executing")

    run.status = "running"
    run.ran_at = datetime.utcnow()
    run.processed_rows = 0
    run.total_rows = 0
    run.error_message = None
    db.commit()
    job_queue.submit_validation(run_id)
    return JSONResponse({"run_id": str(run_id), "status": "running"}, status_code=202)


@router.get("/{run_id}/result")
def get_result(run_id: uuid.UUID, db: Session = Depends(get_db),
                current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)
    project = db.get(ValidationProject, run.project_id)
    exceptions = db.query(ValidationException).filter_by(run_id=run_id).all()

    invalid_share = (
        f"{round((run.invalid_rows / run.total_records) * 100, 1)}% of total dataset"
        if run.total_records else "0% of total dataset"
    )
    avg_errors = (
        f"Avg {round(run.total_errors / run.invalid_rows, 1)} errors per invalid row"
        if run.invalid_rows else "No invalid rows"
    )

    return {
        "id": str(run.id),
        "projectLabel": project.name if project else "",
        "projectName": project.name if project else "",
        "runName": run.name,
        "healthScore": float(run.health_score),
        "processedRecords": run.total_records,
        "validRows": run.valid_rows,
        "validRowsDelta": "",  # no prior-run comparison wired up yet
        "invalidRows": run.invalid_rows,
        "invalidRowsShare": invalid_share,
        "totalErrors": run.total_errors,
        "avgErrorsPerInvalid": avg_errors,
        "criticalErrors": run.critical_errors,
        "errorsByType": run.errors_by_type,
        "errorsByField": run.errors_by_field,
        "status": run.status,
        "processedRows": run.processed_rows or 0,
        "totalRows": run.total_rows or 0,
        "errorMessage": run.error_message,
        "hasResultFile": bool(run.result_s3_key),
        "exceptions": [{
            "id": str(e.id),
            "severity": e.severity,
            "rowId": f"ROW_{e.row_number}",
            "field": e.field_name,
            "actualValue": e.actual_value,
            "expected": e.expected_value,
            "errorType": e.error_type,
            "actionLabel": "Fix" if e.severity == "error" else "View",
        } for e in exceptions],
    }


@router.get("/{run_id}/download-url")
def download_url(run_id: uuid.UUID, db: Session = Depends(get_db),
                  current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)
    if not run.result_s3_key:
        raise HTTPException(404, "Result not ready yet")
    return {"url": s3_service.presigned_url(run.result_s3_key)}
