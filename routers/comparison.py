import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from auth import get_current_user
from db.database import get_db
from db.models import (
    ComparisonDiscrepancy,
    ComparisonRun,
    FinalMapping,
    Mapping,
    User,
    ValidationProject,
)
from routers.mapping import confirmed_counts
from schemas import (
    ComparisonDiscrepancyOut,
    ComparisonReviewOut,
    CreateComparisonRequest,
    ExecuteComparisonRequest,
)
from services import comparison_file_service, job_queue, s3_service

router = APIRouter(prefix="/api/comparisons", tags=["comparison"])
logger = logging.getLogger(__name__)

_VALID_STATUSES = ("draft", "running", "completed", "failed")


def _get_owned_run(run_id: uuid.UUID, db: Session, current_user: User) -> ComparisonRun:
    run = db.get(ComparisonRun, run_id)
    if not run:
        raise HTTPException(404, "Comparison run not found")
    project = db.get(ValidationProject, run.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Comparison run not found")
    return run


def _list_status(value: str | None) -> str:
    return value if value in _VALID_STATUSES else "draft"


@router.get("/")
def list_comparisons(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Comparison runs across every project owned by the current user."""
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
            "records": f"{run.total_preload_rows or 0} records",
            "mismatches": (run.different_count or 0) + (run.missing_count or 0),
            "projectId": str(project.id),
            "projectName": project.name,
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

    run = ComparisonRun(project_id=project_id, name=payload.name, created_by=current_user.id)
    db.add(run)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail="A comparison run with this name already exists in this project",
        )
    db.refresh(run)
    return {"run_id": str(run.id)}


@router.post("/{run_id}/upload")
async def upload_files(
    run_id: uuid.UUID,
    preload_file: UploadFile = File(...),
    postload_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)

    for upload in (preload_file, postload_file):
        if not comparison_file_service.is_xlsx(upload.filename):
            raise HTTPException(400, f"'{upload.filename}' is not an .xlsx file")

    preload_bytes = await preload_file.read()
    postload_bytes = await postload_file.read()

    try:
        preload_fields = comparison_file_service.read_header(preload_bytes)
        postload_fields = comparison_file_service.read_header(postload_bytes)
    except Exception as exc:
        raise HTTPException(400, f"Could not read the uploaded workbooks: {exc}")

    if not preload_fields or not postload_fields:
        raise HTTPException(400, "Both files need a header row with column names")

    preload_key = f"comparisons/{run_id}/preload/{preload_file.filename}"
    postload_key = f"comparisons/{run_id}/postload/{postload_file.filename}"
    s3_service.upload_bytes(preload_key, preload_bytes, comparison_file_service.XLSX_CONTENT_TYPE)
    s3_service.upload_bytes(postload_key, postload_bytes, comparison_file_service.XLSX_CONTENT_TYPE)

    run.preload_filename = preload_file.filename
    run.preload_s3_key = preload_key
    run.postload_filename = postload_file.filename
    run.postload_s3_key = postload_key
    run.status = "draft"
    db.commit()

    return {"preload_fields": preload_fields, "postload_fields": postload_fields}


@router.get("/{run_id}/available-mappings")
def available_mappings(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Confirmed mappings in the same project that can drive this comparison."""
    run = _get_owned_run(run_id, db, current_user)
    mappings = (
        db.query(Mapping)
        .filter(Mapping.project_id == run.project_id, Mapping.status == "completed")
        .order_by(Mapping.created_at.desc())
        .all()
    )

    result = []
    for mapping in mappings:
        confirmed_field_count, key_field_count = confirmed_counts(db, mapping.id)
        if not confirmed_field_count:
            continue
        result.append({
            "id": str(mapping.id),
            "name": mapping.mapping_name,
            "confirmedFieldCount": confirmed_field_count,
            "keyFieldCount": key_field_count,
            "createdAt": mapping.created_at.isoformat() if mapping.created_at else None,
        })
    return result


@router.post("/{run_id}/execute")
def execute_comparison(
    run_id: uuid.UUID,
    payload: ExecuteComparisonRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    if not run.preload_s3_key or not run.postload_s3_key:
        raise HTTPException(400, "Upload both a preload and a postload file first")
    if run.status == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "This comparison is already executing")

    mapping_rows = None
    if payload.mapping_id:
        mapping = db.get(Mapping, payload.mapping_id)
        if not mapping or mapping.project_id != run.project_id:
            raise HTTPException(404, "Mapping run not found in this project")
        confirmed = db.query(FinalMapping).filter_by(mapping_id=mapping.id).all()
        if not confirmed:
            raise HTTPException(422, "That mapping has no confirmed fields yet")
        mapping_rows = [
            {
                "source_field": row.source_field,
                "target_field": row.target_field,
                "is_key": bool(row.key),
            }
            for row in confirmed
        ]
        if not any(row["is_key"] for row in mapping_rows):
            raise HTTPException(
                422,
                "The selected mapping has no key field. Key fields come from the key column "
                "of the uploaded source schema, so re-run the mapping with keys flagged there.",
            )

    run.mapping_id = payload.mapping_id
    run.business_key_columns_preload = payload.business_key_columns_preload
    run.business_key_columns_postload = payload.business_key_columns_postload
    run.status = "running"
    run.ran_at = datetime.utcnow()
    db.commit()
    job_queue.submit_comparison(run_id)
    return JSONResponse({"run_id": str(run_id), "status": "running"}, status_code=202)


@router.get("/{run_id}/result", response_model=ComparisonReviewOut)
def get_result(
    run_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    run = _get_owned_run(run_id, db, current_user)
    project = db.get(ValidationProject, run.project_id)
    rows = (
        db.query(ComparisonDiscrepancy)
        .filter_by(run_id=run_id)
        .order_by(ComparisonDiscrepancy.row_number)
        .all()
    )

    return ComparisonReviewOut(
        id=str(run.id),
        projectName=project.name if project else "",
        runName=run.name,
        status=_list_status(run.status),
        matchedRecords=run.matched_records or 0,
        matchRate=f"{float(run.match_rate or 0):.1f}% Match Rate",
        differentCount=run.different_count or 0,
        differentLabel="Value Mismatches Detected",
        missingCount=run.missing_count or 0,
        missingLabel="Dropped or extra records",
        discrepancies=[
            ComparisonDiscrepancyOut(
                id=str(row.id),
                businessKey=row.business_key,
                field=row.field_name,
                fieldItalic=bool(row.field_italic),
                preloadValue=row.preload_value or "",
                postloadValue=row.postload_value or "",
                postloadHighlight=(
                    "error"
                    if row.difference_type in ("DROPPED_RECORD", "EXTRA_RECORD")
                    else "tertiary"
                ),
                differenceType=row.difference_type,
                status=row.severity or "warning",
            )
            for row in rows
        ],
    )


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
