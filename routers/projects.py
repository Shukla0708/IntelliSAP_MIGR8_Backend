import uuid
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from db.database import get_db
from db.models import User, ValidationProject, ValidationRun
from auth import get_current_user
from schemas import ProjectCreate, ProjectOut

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
        "status": r.status if r.status in ("completed", "failed", "running") else "running",
        "errors": r.total_errors,
    } for r in runs]
