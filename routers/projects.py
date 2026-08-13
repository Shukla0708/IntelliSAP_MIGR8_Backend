import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User, ValidationProject, ValidationRun
from auth import get_current_user
from schemas import ProjectCreate, ProjectOut
from schemas.reports import (
    ProjectReportOut,
    ReportErrorByField,
    ReportErrorByType,
    ReportProject,
    ReportReadiness,
    ReportRecentRun,
    ReportValidationSection,
)

router = APIRouter(prefix="/api/projects", tags=["projects"])


@router.post("/", response_model=ProjectOut)
def create_project(payload: ProjectCreate, db: Session = Depends(get_db),
                    current_user: User = Depends(get_current_user)):
    project = ValidationProject(user_id=current_user.id, name=payload.name)
    db.add(project)
    db.commit()
    db.refresh(project)
    return ProjectOut(id=str(project.id), name=project.name, created_at=project.created_at)


@router.get("/", response_model=list[ProjectOut])
def list_projects(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    projects = (
        db.query(ValidationProject)
        .filter(ValidationProject.user_id == current_user.id)
        .order_by(ValidationProject.created_at.desc())
        .all()
    )
    return [
        ProjectOut(id=str(p.id), name=p.name, created_at=p.created_at)
        for p in projects
    ]


def _get_owned_project(project_id: uuid.UUID, db: Session, current_user: User) -> ValidationProject:
    project = db.get(ValidationProject, project_id)
    if not project or project.user_id != current_user.id:
        raise HTTPException(404, "Project not found")
    return project


def _list_status(status: str | None) -> str:
    if status in ("completed", "failed", "running"):
        return status
    return "running"


def _merge_error_counts(items: list | None, key_field: str) -> list[tuple[str, int]]:
    totals: dict[str, int] = defaultdict(int)
    for item in items or []:
        if not isinstance(item, dict):
            continue
        label = item.get(key_field) or item.get("label")
        count = item.get("count") or item.get("value") or 0
        if label:
            totals[str(label)] += int(count)
    return sorted(totals.items(), key=lambda pair: pair[1], reverse=True)


@router.get("/{project_id}/report", response_model=ProjectReportOut)
def get_project_report(
    project_id: uuid.UUID,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    project = _get_owned_project(project_id, db, current_user)
    runs = (
        db.query(ValidationRun)
        .filter(ValidationRun.project_id == project_id)
        .order_by(ValidationRun.created_at.desc())
        .all()
    )

    completed = [r for r in runs if r.status == "completed"]
    failed = [r for r in runs if r.status == "failed"]
    in_progress = [r for r in runs if r.status not in ("completed", "failed")]

    total_records = sum(r.total_records or 0 for r in completed)
    valid_rows = sum(r.valid_rows or 0 for r in completed)
    invalid_rows = sum(r.invalid_rows or 0 for r in completed)
    total_errors = sum(r.total_errors or 0 for r in completed)
    critical_errors = sum(r.critical_errors or 0 for r in completed)

    health_scores = [float(r.health_score or 0) for r in completed if r.health_score is not None]
    avg_health = round(sum(health_scores) / len(health_scores), 1) if health_scores else 0.0
    pass_rate = round((valid_rows / total_records) * 100, 1) if total_records else 0.0

    type_totals: dict[str, int] = defaultdict(int)
    field_totals: dict[str, int] = defaultdict(int)
    for run in completed:
        for label, count in _merge_error_counts(run.errors_by_type, "label"):
            type_totals[label] += count
        for field, count in _merge_error_counts(run.errors_by_field, "field"):
            field_totals[field] += count

    errors_by_type = [
        ReportErrorByType(label=label, value=count)
        for label, count in sorted(type_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    ]
    errors_by_field = [
        ReportErrorByField(field=field, count=count)
        for field, count in sorted(field_totals.items(), key=lambda x: x[1], reverse=True)[:5]
    ]

    recent_runs = [
        ReportRecentRun(
            id=str(r.id),
            name=r.name,
            status=_list_status(r.status),
            healthScore=float(r.health_score or 0),
            totalErrors=r.total_errors or 0,
            totalRecords=r.total_records or 0,
            ranAt=r.ran_at,
        )
        for r in runs[:8]
    ]

    validation_section = ReportValidationSection(
        totalRuns=len(runs),
        completedRuns=len(completed),
        failedRuns=len(failed),
        inProgressRuns=len(in_progress),
        totalRecords=total_records,
        validRows=valid_rows,
        invalidRows=invalid_rows,
        totalErrors=total_errors,
        criticalErrors=critical_errors,
        avgHealthScore=avg_health,
        passRate=pass_rate,
        errorsByType=errors_by_type,
        errorsByField=errors_by_field,
        recentRuns=recent_runs,
    )

    return ProjectReportOut(
        project=ReportProject(
            id=str(project.id),
            name=project.name,
            created_at=project.created_at,
        ),
        generatedAt=datetime.utcnow(),
        readiness=ReportReadiness(
            score=avg_health,
            validation=avg_health,
            comparison=0.0,
            mapping=0.0,
        ),
        validation=validation_section,
    )


@router.get("/{project_id}/runs")
def list_project_runs(project_id: uuid.UUID, db: Session = Depends(get_db),
                       current_user: User = Depends(get_current_user)):
    _get_owned_project(project_id, db, current_user)
    runs = (
        db.query(ValidationRun)
        .filter(ValidationRun.project_id == project_id)
        .order_by(ValidationRun.created_at.desc())
        .all()
    )
    return [{
        "id": str(r.id),
        "name": r.name,
        "records": f"{r.total_records} records",
        "ranAt": r.ran_at.isoformat() if r.ran_at else None,
        "status": _list_status(r.status),
        "errors": r.total_errors,
    } for r in runs]
