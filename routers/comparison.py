import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status, Body
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user
from db.database import get_db
from db.models import ComparisonException, ComparisonRun, Mapping, User, ValidationProject
from schemas.comparison import CreateComparisonRequest, ExecuteComparisonRequest
from services import file_stream, job_queue, s3_service

router = APIRouter(prefix="/api/comparisons", tags=["comparison"])

_VALID_STATUSES = ("draft", "running", "completed", "failed")


def _get_owned_run(run_id: uuid.UUID, db: Session, current_user: User) -> ComparisonRun:
    run = db.get(ComparisonRun, run_id)
    if not run:
        raise HTTPException(404, "Comparison not found")
    project = db.get(ValidationProject, run.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Comparison not found")
    return run


def _list_status(value: str | None) -> str:
    if value in _VALID_STATUSES:
        return value
    return "draft"


def _store_upload(run_id: uuid.UUID, side: str, upload: UploadFile) -> tuple[str, str, list[str]]:
    filename = upload.filename or f"{side}.xlsx"
    try:
        file_stream.sniff_kind(filename)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    key = f"comparisons/{run_id}/{side}/{filename}"
    s3_service.upload_fileobj(
        key, upload.file, upload.content_type or "application/octet-stream",
    )
    stored = s3_service.local_path_if_exists(key)
    if stored:
        headers = file_stream.extract_headers_from_path(stored, filename)
    else:
        tmp = s3_service.download_to_temp(key, suffix="." + filename.rsplit(".", 1)[-1])
        try:
            headers = file_stream.extract_headers_from_path(tmp, filename)
        finally:
            tmp.unlink(missing_ok=True)
    if not headers:
        raise HTTPException(422, f"No column headers found in the {side} file.")
    return filename, key, headers


@router.get("/")
def list_comparisons(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    limit = max(1, min(limit, 200))
    offset = max(0, offset)
    query = (
        db.query(ComparisonRun, ValidationProject)
        .join(ValidationProject, ComparisonRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
    )
    if project_id is not None:
        query = query.filter(ComparisonRun.project_id == project_id)
    rows = (
        query.order_by(ComparisonRun.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return [
        {
            "id": str(run.id),
            "name": run.name,
            "status": _list_status(run.status),
            "ranAt": run.ran_at.isoformat() if run.ran_at else None,
            "records": f"{run.total_rows or 0} records",
            "mismatches": (run.different_count or 0) + (run.missing_count or 0) + (run.extra_count or 0),
            "project_id": str(project.id),
            "project_name": project.name,
        }
        for run, project in rows
    ]


@router.post("/")
def create_comparison(
    project_id: uuid.UUID,
    payload: CreateComparisonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(ValidationProject, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Project not found")
    mapping_id = payload.mapping_id
    if mapping_id:
        mapping = db.get(Mapping, mapping_id)
        if not mapping or mapping.project_id != project_id:
            raise HTTPException(400, "Field mapping was not found in this project")

    run = ComparisonRun(
        project_id=project_id,
        name=payload.name,
        created_by=current_user.id,
        mapping_id=mapping_id,
        join_keys=payload.join_keys or [],
    )
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="A comparison with this name already exists in this project",
        )
    db.refresh(run)
    return {"comparison_id": str(run.id)}


@router.get("/{run_id}")
def get_comparison(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    return {
        "id": str(run.id),
        "project_id": str(run.project_id),
        "name": run.name,
        "status": _list_status(run.status),
        "preload_filename": run.preload_filename,
        "postload_filename": run.postload_filename,
        "has_preload_file": bool(run.preload_s3_key),
        "has_postload_file": bool(run.postload_s3_key),
        "mapping_id": str(run.mapping_id) if run.mapping_id else None,
        "join_keys": run.join_keys or [],
        "processed_rows": run.processed_rows or 0,
        "total_rows": run.total_rows or 0,
        "error_message": run.error_message,
        "has_result_file": bool(run.result_s3_key),
    }


@router.post("/{run_id}/upload")
async def upload_files(
    run_id: uuid.UUID,
    preload_file: UploadFile = File(...),
    postload_file: UploadFile = File(...),
    mapping_id: str | None = Form(None),
    join_keys: str | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    preload_name, preload_key, preload_headers = _store_upload(run_id, "preload", preload_file)
    postload_name, postload_key, postload_headers = _store_upload(run_id, "postload", postload_file)
    run.preload_filename = preload_name
    run.preload_s3_key = preload_key
    run.postload_filename = postload_name
    run.postload_s3_key = postload_key
    if mapping_id:
        run.mapping_id = uuid.UUID(mapping_id)
    if join_keys:
        run.join_keys = [part.strip() for part in join_keys.split(",") if part.strip()]
    run.status = "draft"
    db.commit()
    overlap = sorted(
        {h.lower(): h for h in preload_headers}.keys()
        & {h.lower(): h for h in postload_headers}.keys()
    )
    overlap_names = [
        {h.lower(): h for h in preload_headers}[key] for key in overlap
    ]
    return {
        "preload_headers": preload_headers,
        "postload_headers": postload_headers,
        "shared_headers": overlap_names,
    }


@router.post("/{run_id}/execute")
def execute_comparison(
    run_id: uuid.UUID,
    payload: ExecuteComparisonRequest | None = Body(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    if not run.preload_s3_key or not run.postload_s3_key:
        raise HTTPException(400, "Upload both preload and postload files first")
    if run.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "This comparison is already executing")
    if payload:
        if payload.mapping_id:
            run.mapping_id = payload.mapping_id
        if payload.join_keys is not None:
            run.join_keys = payload.join_keys
    if not run.mapping_id and not (run.join_keys or []):
        raise HTTPException(400, "Select at least one join key, or attach a confirmed field mapping")

    run.status = "running"
    run.ran_at = datetime.utcnow()
    run.processed_rows = 0
    run.total_rows = 0
    run.error_message = None
    db.commit()
    job_queue.submit_comparison(run_id)
    return JSONResponse({"comparison_id": str(run_id), "status": "running"}, status_code=202)


@router.get("/{run_id}/result")
def get_comparison_result(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    project = db.get(ValidationProject, run.project_id)
    exceptions = (
        db.query(ComparisonException)
        .filter_by(run_id=run_id)
        .all()
    )
    return {
        "id": str(run.id),
        "projectName": project.name if project else "",
        "runName": run.name,
        "matchedRecords": run.matched_records or 0,
        "matchRate": f"{float(run.match_rate or 0):.1f}% Match Rate",
        "differentCount": run.different_count or 0,
        "differentLabel": "Value mismatches detected",
        "missingCount": run.missing_count or 0,
        "missingLabel": "Dropped during load",
        "extraCount": run.extra_count or 0,
        "status": _list_status(run.status),
        "processedRows": run.processed_rows or 0,
        "totalRows": run.total_rows or 0,
        "errorMessage": run.error_message,
        "hasResultFile": bool(run.result_s3_key),
        "discrepancies": [
            {
                "id": str(item.id),
                "businessKey": item.business_key,
                "field": item.field_name,
                "fieldItalic": item.field_name == "Entire Record",
                "preloadValue": item.preload_value or "",
                "postloadValue": item.postload_value or "",
                "postloadHighlight": "error" if item.severity == "error" else "tertiary",
                "differenceType": item.difference_type,
                "status": item.severity if item.severity in ("error", "warning", "info") else "warning",
            }
            for item in exceptions
        ],
    }


@router.get("/{run_id}/download-url")
def download_url(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    if not run.result_s3_key:
        raise HTTPException(404, "Result not ready yet")
    return {"url": s3_service.presigned_url(run.result_s3_key)}
