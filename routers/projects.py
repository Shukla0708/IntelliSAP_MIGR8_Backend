import uuid
from collections import defaultdict
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import Float, cast, func
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import (
    ComparisonRun,
    Mapping,
    MappingTemp,
    User,
    ValidationProject,
    ValidationRun,
)
from auth import get_current_user
from routers.mapping import _confirmed_counts_by_ids, _public_status
from schemas import ProjectCreate, ProjectOut
from schemas.reports import (
    ProjectReportOut,
    ReportComparisonSection,
    ReportErrorByField,
    ReportErrorByType,
    ReportMappingSection,
    ReportProject,
    ReportReadiness,
    ReportRecentComparisonRun,
    ReportRecentMappingRun,
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
    if status in ("draft", "rules_configured", "running", "completed", "failed"):
        return status
    return "draft"


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
        .limit(100)
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

    comparison_section = _comparison_report(db, project_id)
    mapping_section = _mapping_report(db, project_id)
    readiness = _composite_readiness(
        avg_health,
        comparison_section.avgMatchRate,
        mapping_section.approvalRate,
    )

    return ProjectReportOut(
        project=ReportProject(
            id=str(project.id),
            name=project.name,
            created_at=project.created_at,
        ),
        generatedAt=datetime.utcnow(),
        readiness=readiness,
        validation=validation_section,
        comparison=comparison_section,
        mapping=mapping_section,
    )


def _composite_readiness(
    validation: float, comparison: float, mapping: float
) -> ReportReadiness:
    score = round(validation * 0.5 + comparison * 0.25 + mapping * 0.25)
    return ReportReadiness(
        score=score,
        validation=validation,
        comparison=comparison,
        mapping=mapping,
    )


def _comparison_report(db: Session, project_id: uuid.UUID) -> ReportComparisonSection:
    runs = (
        db.query(ComparisonRun)
        .filter(ComparisonRun.project_id == project_id)
        .order_by(ComparisonRun.created_at.desc())
        .limit(50)
        .all()
    )
    completed = [r for r in runs if r.status == "completed"]
    total_mismatches = sum(
        (r.different_count or 0) + (r.missing_count or 0) for r in runs
    )
    match_rates = [float(r.match_rate or 0) for r in completed]
    avg_match = round(sum(match_rates) / len(match_rates)) if match_rates else 0

    return ReportComparisonSection(
        totalRuns=len(runs),
        completedRuns=len(completed),
        totalMismatches=total_mismatches,
        avgMatchRate=avg_match,
        matchedRecords=sum(r.matched_records or 0 for r in completed),
        differentCount=sum(r.different_count or 0 for r in completed),
        missingCount=sum(r.missing_count or 0 for r in completed),
        recentRuns=[
            ReportRecentComparisonRun(
                id=str(r.id),
                name=r.name,
                status=r.status or "draft",
                mismatches=(r.different_count or 0) + (r.missing_count or 0),
                records=f"{r.total_preload_rows or 0} records",
                ranAt=r.ran_at,
            )
            for r in runs[:8]
        ],
    )


def _mapping_report(db: Session, project_id: uuid.UUID) -> ReportMappingSection:
    runs = (
        db.query(Mapping)
        .filter(Mapping.project_id == project_id)
        .order_by(Mapping.created_at.desc())
        .limit(50)
        .all()
    )
    counts = _confirmed_counts_by_ids(db, [run.id for run in runs])
    total_fields = sum(run.total_source_fields or 0 for run in runs)
    confirmed_fields = sum(counts.get(run.id, (0, 0))[0] for run in runs)
    unmapped = max(total_fields - confirmed_fields, 0)
    approval_rate = round((confirmed_fields / total_fields) * 100) if total_fields else 0
    completed_count = 0
    recent = []
    for run in runs:
        confirmed, _ = counts.get(run.id, (0, 0))
        public = _public_status(run.status or "processing", confirmed)
        if public == "completed":
            completed_count += 1
        if len(recent) < 8:
            recent.append(
                ReportRecentMappingRun(
                    id=str(run.id),
                    name=run.mapping_name or "Field mapping run",
                    status=public,
                    unmapped=max((run.total_source_fields or 0) - confirmed, 0),
                    fields=f"{run.total_source_fields or 0} fields",
                    ranAt=run.created_at,
                )
            )

    return ReportMappingSection(
        totalRuns=len(runs),
        completedRuns=completed_count,
        totalFields=total_fields,
        unmappedFields=unmapped,
        approvalRate=approval_rate,
        avgConfidence=_avg_mapping_confidence(db, [run.id for run in runs[:3]]),
        recentRuns=recent,
    )


def _avg_mapping_confidence(db: Session, mapping_ids: list[uuid.UUID]) -> float:
    if not mapping_ids:
        return 0.0
    score_expr = cast(MappingTemp.mapping[0]["confidence_score"].astext, Float)
    avg = (
        db.query(func.avg(score_expr))
        .filter(MappingTemp.mapping_id.in_(mapping_ids))
        .scalar()
    )
    return round(float(avg)) if avg is not None else 0.0


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
