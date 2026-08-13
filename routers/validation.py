import uuid
from datetime import datetime
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException, status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User, ValidationRun, ValidationField, ValidationException, ValidationProject
from auth import get_current_user
from services import excel_service, s3_service, regex_generator
from schemas import CreateRunRequest, FieldRuleIn, RegexGenerateRequest, RegexGenerateResponse

router = APIRouter(prefix="/api/runs", tags=["validation"])


def _get_owned_run(run_id: uuid.UUID, db: Session, current_user: User) -> ValidationRun:
    run = db.get(ValidationRun, run_id)
    if not run:
        raise HTTPException(404, "Run not found")
    project = db.get(ValidationProject, run.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Run not found")
    return run


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


@router.post("/{run_id}/upload")
async def upload_source(run_id: uuid.UUID, file: UploadFile = File(...),
                         db: Session = Depends(get_db),
                         current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)

    content = await file.read()
    key = f"validations/{run_id}/source/{file.filename}"
    s3_service.upload_bytes(key, content, file.content_type or "application/octet-stream")

    fields = excel_service.extract_headers(content)

    db.query(ValidationField).filter(ValidationField.run_id == run_id).delete()
    for idx, name in enumerate(fields):
        db.add(ValidationField(run_id=run_id, field_name=name, column_index=idx))

    run.source_filename = file.filename
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
        # If the user wrote a plain-English rule, always ask Groq for the regex
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


@router.post("/generate-regex", response_model=RegexGenerateResponse)
def generate_regex_route(payload: RegexGenerateRequest, current_user: User = Depends(get_current_user)):
    try:
        regex = regex_generator.generate_regex(payload.field_name, payload.prompt)
        return RegexGenerateResponse(regex=regex)
    except Exception:
        raise HTTPException(422, "Could not generate a valid rule from that prompt. Try rephrasing it.")


@router.post("/{run_id}/execute")
def execute_run(run_id: uuid.UUID, db: Session = Depends(get_db),
                 current_user: User = Depends(get_current_user)):
    run = _get_owned_run(run_id, db, current_user)
    if not run.source_s3_key:
        raise HTTPException(400, "No source file uploaded for this run")

    run.status = "running"
    run.ran_at = datetime.utcnow()
    db.commit()

    field_rows = db.query(ValidationField).filter_by(run_id=run_id).all()
    field_configs = [{
        "field_name": f.field_name,
        "flag_key": f.flag_key, "flag_mandatory": f.flag_mandatory,
        "flag_null": f.flag_null, "flag_email": f.flag_email,
        "flag_mobile": f.flag_mobile, "flag_date": f.flag_date,
        "flag_special_chars": f.flag_special_chars,
        "case_format": f.case_format, "data_type": f.data_type,
        "max_length": f.max_length, "decimal_length": f.decimal_length,
        "regex": f.regex,
    } for f in field_rows]

    try:
        source_bytes = s3_service.download_bytes(run.source_s3_key)
        result_bytes, stats, exceptions = excel_service.run_validation(source_bytes, field_configs)

        result_key = f"validations/{run_id}/result/{run.source_filename}"
        s3_service.upload_bytes(
            result_key, result_bytes,
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        db.query(ValidationException).filter_by(run_id=run_id).delete()
        for e in exceptions:
            db.add(ValidationException(run_id=run_id, **e))

        for k, v in stats.items():
            setattr(run, k, v)
        run.result_s3_key = result_key
        run.status = "completed"
        run.completed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:
        run.status = "failed"
        db.commit()
        raise HTTPException(500, f"Validation run failed: {exc}")

    return {"run_id": str(run_id), "status": "completed"}


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
