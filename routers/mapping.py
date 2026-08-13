import uuid
from fastapi import APIRouter, UploadFile, File, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User, ValidationProject, Mapping, MappingTemp, FinalMapping
from auth import get_current_user
from schemas import ConfirmMappingRequest
from services import s3_service, file_parser, mapping_engine, llm_mapping

router = APIRouter(prefix="/api/mappings", tags=["field-mapping"])


def _get_owned_mapping(run_id: uuid.UUID, db: Session, current_user: User) -> Mapping:
    id = run_id
    print(run_id)
    mapping = db.get(Mapping, id)
    print(mapping)
    if not mapping:
        raise HTTPException(404, "Mapping run not found")
    project = db.get(ValidationProject, mapping.project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Mapping run not found")
    return mapping


def _serialize(mapping: Mapping, temp_rows: list[MappingTemp]) -> dict:
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
        } for c in (t.mapping or [])]
        rows.append({"sourceField": t.source_field, "prospects": prospects})

    return {
        "mappingRunId": str(mapping.id),
        "status": mapping.status,
        "sourceFilename": mapping.source_filename,
        "targetFilename": mapping.target_filename,
        "totalSourceFields": mapping.total_source_fields,
        "mappedFields": mapping.mapped_fields,
        "rows": rows,
    }


@router.post("/")
async def create_mapping_run(
    project_id: uuid.UUID,
    source_file: UploadFile = File(...),
    target_file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = db.get(ValidationProject, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Project not found")

    mapping = Mapping(project_id=project_id, status="processing")
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

    try:
        source_fields = file_parser.parse_source_fields(source_bytes, source_file.filename)
        target_fields = file_parser.parse_target_fields(target_bytes, target_file.filename)
        if not source_fields:
            raise ValueError("Source field list is empty")
        if not target_fields:
            raise ValueError("Target SAP field list is empty")

        raw_matches = mapping_engine.top_candidates(source_fields, target_fields)

        db.query(MappingTemp).filter_by(mapping_id=mapping.id).delete()
        mapped_fields = 0
        for match in raw_matches:
            try:
                final_candidates = llm_mapping.rank_candidates(
                    match["source_field"], match["source_description"], match["candidates"]
                )
            except Exception:
                # LLM unavailable/invalid response — fall back to embedding-only ranking
                final_candidates = [{
                    "sap_table": c["sap_table"],
                    "sap_field": c["sap_field"],
                    "target_description": c.get("target_description"),
                    "embedding_score": c["embedding_score"],
                    "datatype_match_score": c.get("datatype_match_score"),
                    "confidence_score": round(c["embedding_score"] * 100, 2),
                    "reasoning": "LLM ranking unavailable; ranked by embedding similarity only.",
                } for c in match["candidates"]]

            if final_candidates:
                mapped_fields += 1

            db.add(MappingTemp(
                mapping_id=mapping.id,
                source_field=match["source_field"],
                mapping=final_candidates,
            ))

        mapping.total_source_fields = len(source_fields)
        mapping.mapped_fields = mapped_fields
        mapping.status = "completed"
        db.commit()
    except Exception as exc:
        mapping.status = "failed"
        db.commit()
        raise HTTPException(422, f"Field mapping failed: {exc}")

    temp_rows = db.query(MappingTemp).filter_by(mapping_id=mapping.id).all()
    return _serialize(mapping, temp_rows)


@router.get("/{run_id}/result")
def get_mapping_result(run_id: uuid.UUID, db: Session = Depends(get_db),
                        current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)
    temp_rows = db.query(MappingTemp).filter_by(mapping_id=run_id).all()
    return _serialize(mapping, temp_rows)


@router.post("/{run_id}/confirm")
def confirm_mapping(run_id: uuid.UUID, payload: ConfirmMappingRequest, db: Session = Depends(get_db),
                     current_user: User = Depends(get_current_user)):
    mapping = _get_owned_mapping(run_id, db, current_user)

    temp_by_field = {t.source_field: t for t in db.query(MappingTemp).filter_by(mapping_id=mapping.id).all()}

    confirmed = []
    for item in payload.fields:
        temp = temp_by_field.get(item.source_field)
        if temp is None:
            raise HTTPException(404, f"Source field '{item.source_field}' not found in this mapping run")

        candidate_keys = {f"{c['sap_table']}.{c['sap_field']}" for c in (temp.mapping or [])}
        if item.target_field not in candidate_keys:
            raise HTTPException(
                422, f"'{item.target_field}' is not a suggested candidate for '{item.source_field}'"
            )

        existing = db.query(FinalMapping).filter_by(
            mapping_id=mapping.id, source_field=item.source_field
        ).first()
        if existing:
            existing.target_field = item.target_field
        else:
            existing = FinalMapping(
                mapping_id=mapping.id, source_field=item.source_field, target_field=item.target_field
            )
            db.add(existing)
        confirmed.append(existing)

    db.commit()
    return {
        "mappingRunId": str(mapping.id),
        "confirmed": [{"sourceField": c.source_field, "targetField": c.target_field} for c in confirmed],
    }
