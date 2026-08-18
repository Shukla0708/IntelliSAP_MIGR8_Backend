"""One-shot dashboard payload — KPI totals, activity, mapping stats, recent projects."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy import case, func
from sqlalchemy.orm import Session

from auth import get_current_user
from db.database import get_db
from db.models import (
    ComparisonRun,
    FinalMapping,
    Mapping,
    User,
    ValidationProject,
    ValidationRun,
)
from routers.mapping import _public_status

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects = (
        db.query(ValidationProject)
        .filter(ValidationProject.user_id == current_user.id)
        .order_by(ValidationProject.created_at.desc())
        .all()
    )
    project_ids = [p.id for p in projects]

    val_totals = (
        db.query(
            func.count(ValidationRun.id),
            func.coalesce(func.sum(ValidationRun.total_records), 0),
            func.coalesce(func.sum(ValidationRun.total_errors), 0),
            func.coalesce(
                func.sum(case((ValidationRun.status == "completed", 1), else_=0)),
                0,
            ),
            func.coalesce(
                func.sum(case((ValidationRun.status == "failed", 1), else_=0)),
                0,
            ),
        )
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .one()
    )
    run_count, records, errors, completed, failed = (int(v or 0) for v in val_totals)

    cmp_totals = (
        db.query(
            func.count(ComparisonRun.id),
            func.coalesce(func.sum(ComparisonRun.different_count), 0),
            func.coalesce(func.sum(ComparisonRun.missing_count), 0),
            func.coalesce(
                func.sum(case((ComparisonRun.status == "completed", 1), else_=0)),
                0,
            ),
        )
        .join(ValidationProject, ComparisonRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .one()
    )
    cmp_count, different, missing, cmp_completed = (int(v or 0) for v in cmp_totals)
    mismatches = different + missing

    mapping_rows = (
        db.query(Mapping.id, Mapping.status)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .all()
    )
    confirmed_ids = set()
    if mapping_rows:
        confirmed_ids = {
            mapping_id
            for (mapping_id,) in db.query(FinalMapping.mapping_id)
            .filter(FinalMapping.mapping_id.in_([row.id for row in mapping_rows]))
            .distinct()
            .all()
        }
    approved = awaiting_approval = processing = mapping_failed = 0
    for mapping_id, status in mapping_rows:
        public = _public_status(status, 1 if mapping_id in confirmed_ids else 0)
        if public == "completed":
            approved += 1
        elif public == "awaiting_approval":
            awaiting_approval += 1
        elif public == "failed":
            mapping_failed += 1
        else:
            processing += 1
    mapping_stats = {
        "approved": approved,
        "awaitingApproval": awaiting_approval,
        "processing": processing,
        "failed": mapping_failed,
        "total": len(mapping_rows),
    }

    run_counts = {}
    record_totals = {}
    if project_ids:
        run_counts = dict(
            db.query(ValidationRun.project_id, func.count(ValidationRun.id))
            .filter(ValidationRun.project_id.in_(project_ids))
            .group_by(ValidationRun.project_id)
            .all()
        )
        record_totals = dict(
            db.query(ValidationRun.project_id, func.coalesce(func.sum(ValidationRun.total_records), 0))
            .filter(ValidationRun.project_id.in_(project_ids))
            .group_by(ValidationRun.project_id)
            .all()
        )

    recent_projects = []
    for project in projects[:5]:
        count = int(run_counts.get(project.id) or 0)
        recs = int(record_totals.get(project.id) or 0)
        recent_projects.append({
            "id": str(project.id),
            "name": project.name,
            "runCount": count,
            "records": recs,
            "createdAt": project.created_at.isoformat() if project.created_at else None,
        })

    activity = []
    val_rows = (
        db.query(ValidationRun, ValidationProject)
        .join(ValidationProject, ValidationRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .order_by(ValidationRun.created_at.desc())
        .limit(5)
        .all()
    )
    for run, project in val_rows:
        activity.append({
            "id": f"val-{run.id}",
            "type": "validation",
            "name": run.name,
            "projectName": project.name,
            "href": f"/validation_result/{run.id}",
            "meta": f"{run.total_errors or 0} errors · {run.status}",
        })
    cmp_rows = (
        db.query(ComparisonRun, ValidationProject)
        .join(ValidationProject, ComparisonRun.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .order_by(ComparisonRun.created_at.desc())
        .limit(2)
        .all()
    )
    for run, project in cmp_rows:
        mm = (run.different_count or 0) + (run.missing_count or 0)
        activity.append({
            "id": f"cmp-{run.id}",
            "type": "comparison",
            "name": run.name,
            "projectName": project.name,
            "href": f"/compare/{run.id}",
            "meta": f"{mm} mismatches",
        })
    map_rows = (
        db.query(Mapping, ValidationProject)
        .join(ValidationProject, Mapping.project_id == ValidationProject.id)
        .filter(ValidationProject.user_id == current_user.id)
        .order_by(Mapping.created_at.desc())
        .limit(2)
        .all()
    )
    unmapped_fields = 0
    for run, project in map_rows:
        confirmed = 1 if run.id in confirmed_ids else 0
        public = _public_status(run.status, confirmed)
        confirmed_count = db.query(func.count(FinalMapping.id)).filter_by(mapping_id=run.id).scalar() or 0
        unmapped = max((run.total_source_fields or 0) - int(confirmed_count), 0)
        unmapped_fields += unmapped
        activity.append({
            "id": f"map-{run.id}",
            "type": "mapping",
            "name": run.mapping_name or "New field mapping run",
            "projectName": project.name,
            "href": f"/field-mapping/{run.id}",
            "meta": "Waiting for approval" if public == "awaiting_approval" else f"{unmapped} unmapped",
        })

    validation_score = round((completed / max(run_count, 1)) * 100) if run_count else 0
    comparison_score = round((cmp_completed / max(cmp_count, 1)) * 100) if cmp_count else 0
    reviewable = approved + awaiting_approval
    mapping_score = round((approved / max(reviewable, 1)) * 100) if reviewable else 0
    readiness = round((validation_score + comparison_score + mapping_score) / 3)

    return {
        "kpis": {
            "activeProjects": len(projects),
            "validationRuns": run_count,
            "completedRuns": completed,
            "recordsValidated": records,
            "validationErrors": errors,
            "comparisonMismatches": mismatches,
            "failedRuns": failed,
            "unmappedFields": unmapped_fields,
        },
        "mappingStats": mapping_stats,
        "readiness": {
            "score": readiness,
            "validation": validation_score,
            "comparison": comparison_score,
            "mapping": mapping_score,
            "failed": failed,
        },
        "recentProjects": recent_projects,
        "activity": activity[:8],
    }
