import uuid
from fastapi import APIRouter, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import case, func
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from db.database import get_db
from db.models import User, ValidationProject, Mapping, MappingTemp, FinalMapping
from auth import get_current_user
from schemas import ConfirmMappingRequest, RenameMappingRequest
from services import job_queue, s3_service, file_parser

NUMBER_RANGE_TYPES = ("internal", "external")
DEFAULT_MAPPING_NAME = "New field mapping run"
MAX_MAPPING_NAME_LENGTH = 120

router = APIRouter(prefix="/api/mappings", tags=["field-mapping"])


def _get_owned_mapping(run_id: uuid.UUID, db: Session, current_user: User) -> Mapping:
    mapping = db.get(Mapping, run_id)
    if not mapping:
        raise HTTPException(404, "Mapping run not found")
    project = db.get(ValidationProject, mapping.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Mapping run not found")
    return mapping


def _clean_mapping_name(raw: str | None) -> str | None:
    """Trimmed run name, or None when the caller left it blank."""
    name = (raw or "").strip()
    if not name:
        return None
    if len(name) > MAX_MAPPING_NAME_LENGTH:
        raise HTTPException(422, f"Mapping name must be at most {MAX_MAPPING_NAME_LENGTH} characters")
    return name


def _target_catalog(mapping: Mapping) -> list[dict]:
    """Every SAP field from the run's uploaded target list, not just the AI's top-3."""
    if not mapping.target_s3_key or not mapping.target_filename:
        raise HTTPException(404, "This mapping run has no stored target field list")
    try:
        target_bytes = s3_service.download_bytes(mapping.target_s3_key)
        return file_parser.parse_target_fields(target_bytes, mapping.target_filename)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(422, f"Could not read the target field list: {exc}")


def _candidate_key(candidate: dict) -> str:
    return f"{candidate.get('sap_table', '')}.{candidate.get('sap_field', '')}"


def _split_target_field(target_field: str) -> tuple[str, str]:
    if "." in target_field:
        table, field = target_field.split(".", 1)
        return table, field
    return "", target_field


def _persist_user_selected_candidate(
    temp: MappingTemp,
    target_field: str,
    catalog_by_key: dict,
) -> None:
    """Keep AI top-3 candidates and persist a pick from outside that list."""
    kept = [c for c in (temp.mapping or []) if not c.get("user_selected")]
    if target_field not in {_candidate_key(c) for c in kept}:
        catalog = catalog_by_key.get(target_field) or {}
        sap_table, sap_field = _split_target_field(target_field)
        kept.append({
            "sap_table": catalog.get("sap_table") or sap_table,
            "sap_field": catalog.get("sap_field") or sap_field,
            "target_description": catalog.get("description"),
            "embedding_score": None,
            "datatype_match_score": None,
            "confidence_score": None,
            "reasoning": "Selected by the user from the full target list.",
            "user_selected": True,
        })
    temp.mapping = kept
    flag_modified(temp, "mapping")


def _confirmed_counts_by_ids(
    db: Session, mapping_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[int, int]]:
    """Batch (confirmed fields, key fields) for many mapping runs in one query."""
    if not mapping_ids:
        return {}
    rows = (
        db.query(
            FinalMapping.mapping_id,
            func.count(FinalMapping.id),
            func.coalesce(func.sum(case((FinalMapping.key.is_(True), 1), else_=0)), 0),
        )
        .filter(FinalMapping.mapping_id.in_(mapping_ids))
        .group_by(FinalMapping.mapping_id)
        .all()
    )
    return {
        mapping_id: (int(confirmed), int(key_count))
        for mapping_id, confirmed, key_count in rows
    }


def confirmed_counts(db: Session, mapping_id: uuid.UUID) -> tuple[int, int]:
    """(confirmed fields, key fields) — key fields form the comparison business key."""
    return _confirmed_counts_by_ids(db, [mapping_id]).get(mapping_id, (0, 0))


def _public_status(status: str, confirmed_field_count: int) -> str:
    """Older runs were stored as completed before approval existed."""
    if status == "completed" and confirmed_field_count == 0:
        return "awaiting_approval"
    return status


def _serialize(mapping: Mapping, temp_rows: list[MappingTemp], confirmed_by_field: dict | None = None) -> dict:
    confirmed_by_field = confirmed_by_field or {}
    rows = []
    for t in temp_rows:
        prospects = [{
            "targetField": f"{c['sap_table']}.{c['sap_field']}",
            "sapTable": c["sap_table"],
            "sapField": c["sap_field"],
            "targetDescription": c.get("target_description"),
            "semanticSimilarity": c.get("embedding_score"),
            "datatypeMatchScore": c.get("datatype_match_score"),
            "confidence": c.get("confidence_score"),
            "reasoning": c.get("reasoning"),
            "userSelected": bool(c.get("user_selected")),
        } for c in (t.mapping or [])]
        rows.append({
            "sourceField": t.source_field,
            "keyField": t.key_field,
            "prospects": prospects,
            "confirmedTargetField": confirmed_by_field.get(t.source_field),
        })

    return {
        "mappingRunId": str(mapping.id),
        "mappingName": mapping.mapping_name,
        "status": _public_status(mapping.status, len(confirmed_by_field)),
        "numberRangeType": mapping.number_range_type,
        "sourceFilename": mapping.source_filename,
        "targetFilename": mapping.target_filename,
        "totalSourceFields": mapping.total_source_fields,
        "mappedFields": mapping.mapped_fields,
        "rows": rows,
    }


@router.get("/")
def list_mapping_runs(
    project_id: uuid.UUID | None = None,
    limit: int = 50,
    offset: int = 0,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mapping runs owned by the caller, newest first. `project_id` narrows to one
    project; the comparison setup screen also reads the key counts from here."""
    if project_id is not None:
        project = db.get(ValidationProject, project_id)
        if not project or project.user_id != current_user.id:
            raise HTTPException(404, "Project not found")

    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    query = (
        db.query(Mapping, ValidationProject)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
    )
    if project_id is not None:
        query = query.filter(Mapping.project_id == project_id)

    rows = query.order_by(Mapping.created_at.desc()).offset(offset).limit(limit).all()
    counts_by_id = _confirmed_counts_by_ids(db, [run.id for run, _ in rows])

    result = []
    for run, project in rows:
        confirmed_field_count, key_field_count = counts_by_id.get(run.id, (0, 0))
        result.append({
            "mappingRunId": str(run.id),
            "mappingName": run.mapping_name,
            "status": _public_status(run.status, confirmed_field_count),
            "projectId": str(project.id),
            "projectName": project.name,
            "sourceFilename": run.source_filename,
            "targetFilename": run.target_filename,
            "totalSourceFields": run.total_source_fields,
            "mappedFields": run.mapped_fields,
            "confirmedFieldCount": confirmed_field_count,
            "keyFieldCount": key_field_count,
            "createdAt": run.created_at.isoformat() if run.created_at else None,
        })
    return result


@router.get("/stats")
def mapping_stats(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Lightweight status counts for the dashboard Mapping Approval KPI."""
    rows = (
        db.query(Mapping.id, Mapping.status)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .all()
    )
    confirmed_ids: set[uuid.UUID] = set()
    if rows:
        confirmed_ids = {
            mapping_id
            for (mapping_id,) in db.query(FinalMapping.mapping_id)
            .filter(FinalMapping.mapping_id.in_([row.id for row in rows]))
            .distinct()
            .all()
        }

    approved = awaiting_approval = processing = failed = 0
    for mapping_id, status in rows:
        public = _public_status(status, 1 if mapping_id in confirmed_ids else 0)
        if public == "completed":
            approved += 1
        elif public == "awaiting_approval":
            awaiting_approval += 1
        elif public == "failed":
            failed += 1
        else:
            processing += 1

    return {
        "approved": approved,
        "awaitingApproval": awaiting_approval,
        "processing": processing,
        "failed": failed,
        "total": len(rows),
    }


@router.post("/")
async def create_mapping_run(
    project_id: uuid.UUID,
    number_range_type: str = Form(...),
    mapping_name: str | None = Form(None),
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if number_range_type not in NUMBER_RANGE_TYPES:
        raise HTTPException(422, "number_range_type must be 'internal' or 'external'")

    project = db.get(ValidationProject, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Project not found")

    mapping = Mapping(
        project_id=project_id,
        mapping_name=_clean_mapping_name(mapping_name) or DEFAULT_MAPPING_NAME,
        status="processing",
        number_range_type=number_range_type,
    )
    db.add(mapping)
    db.commit()
    db.refresh(mapping)

    source_bytes = await source_file.read()
    target_bytes = await target_file.read()

    source_key = f"mappings/{mapping.id}/source/{source_file.filename}"
    target_key = f"mappings/{mapping.id}/target/{target_file.filename}"
    s3_service.upload_bytes(source_key, source_bytes, source_file.content_type or "application/octet-stream")
    s3_service.upload_bytes(target_key, target_bytes, target_file.content_type or "application/octet-stream")

    mapping.source_filename = source_file.filename
    mapping.source_s3_key = source_key
    mapping.target_filename = target_file.filename
    mapping.target_s3_key = target_key
    db.commit()

    job_queue.submit_mapping(mapping.id)
    return JSONResponse(_serialize(mapping, []), status_code=202)


@router.get("/{run_id}/result")
def get_mapping_result(run_id: uuid.UUID, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)
    temp_rows = db.query(MappingTemp).filter_by(mapping_id=run_id).all()
    confirmed_by_field = {
        f.source_field: f.target_field
        for f in db.query(FinalMapping).filter_by(mapping_id=run_id).all()
    }
    return _serialize(mapping, temp_rows, confirmed_by_field)


@router.patch("/{run_id}")
def rename_mapping_run(run_id: uuid.UUID, payload: RenameMappingRequest, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)

    name = _clean_mapping_name(payload.mapping_name)
    if not name:
        raise HTTPException(422, "Mapping name cannot be empty")

    mapping.mapping_name = name
    db.commit()
    return {"mappingRunId": str(mapping.id), "mappingName": mapping.mapping_name}


@router.get("/{run_id}/target-fields")
def list_target_fields(run_id: uuid.UUID, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    """Full SAP target catalog for the run, so users can map outside the top-3."""
    mapping = _get_owned_mapping(run_id, db, current_user)

    return [
        {
            "targetField": f"{t['sap_table']}.{t['sap_field']}",
            "sapTable": t["sap_table"],
            "sapField": t["sap_field"],
            "targetDescription": t.get("description"),
            "datatype": t.get("datatype"),
        }
        for t in _target_catalog(mapping)
    ]
@router.get("/{run_id}/confirmed")
def get_confirmed_mapping(run_id: uuid.UUID, db: Session = Depends(get_db),
                           current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)
    rows = (
        db.query(FinalMapping)
        .filter_by(mapping_id=mapping.id)
        .order_by(FinalMapping.source_field)
        .all()
    )
    return {
        "mappingRunId": str(mapping.id),
        "fields": [{
            "sourceField": row.source_field,
            "targetField": row.target_field,
            "isKey": bool(row.key),
        } for row in rows],
    }


@router.post("/{run_id}/confirm")
def confirm_mapping(run_id: uuid.UUID, payload: ConfirmMappingRequest, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)

    temp_by_field = {t.source_field: t for t in db.query(MappingTemp).filter_by(mapping_id=mapping.id).all()}

    # Users may map to any field in the uploaded target list, not just the AI's
    # top-3, so the catalog is the source of truth here. If it can't be read we
    # fall back to the per-row candidates.
    try:
        catalog_by_key = {
            f"{t['sap_table']}.{t['sap_field']}": t for t in _target_catalog(mapping)
        }
    except HTTPException:
        catalog_by_key = {}
    catalog_keys = set(catalog_by_key)

    confirmed = []
    for item in payload.fields:
        temp = temp_by_field.get(item.source_field)
        if temp is None:
            raise HTTPException(404, f"Source field '{item.source_field}' not found in this mapping run")

        candidate_keys = {_candidate_key(c) for c in (temp.mapping or [])}
        if item.target_field not in candidate_keys and item.target_field not in catalog_keys:
            raise HTTPException(
                422, f"'{item.target_field}' is not a field in this run's target list"
            )

        _persist_user_selected_candidate(temp, item.target_field, catalog_by_key)

        existing = db.query(FinalMapping).filter_by(
            mapping_id=mapping.id, source_field=item.source_field
        ).first()
        if existing:
            existing.target_field = item.target_field
            existing.key = temp.key_field
        else:
            existing = FinalMapping(
                mapping_id=mapping.id,
                source_field=item.source_field,
                target_field=item.target_field,
                key=temp.key_field,
            )
            db.add(existing)
        confirmed.append(existing)

    mapping.status = "completed"
    db.commit()
    return {
        "mappingRunId": str(mapping.id),
        "confirmed": [{
            "sourceField": c.source_field,
            "targetField": c.target_field,
            "isKey": bool(c.key),
        } for c in confirmed],
    }
