from datetime import date
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.modules.projects.models import Category, Project


def commit(db: Session, entity):
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        code = getattr(exc.orig, "sqlstate", None)
        if code == "23505":
            raise HTTPException(409, "The slug or name is already in use") from None
        if code == "23503":
            raise HTTPException(422, "The category does not exist or is in use") from None
        raise
    db.refresh(entity)
    return entity


def category_exists(db: Session, category_id: UUID | None):
    if category_id is not None and db.get(Category, category_id) is None:
        raise HTTPException(422, "Category not found")


def get_project(db: Session, project_id: UUID, version: int | None = None):
    query = select(Project).where(Project.id == project_id)
    if version is not None:
        query = query.with_for_update()
    project = db.scalar(query)
    if project is None:
        raise HTTPException(404, "Project not found")
    if version is not None and project.version != version:
        raise HTTPException(409, "The project changed; reload it before saving")
    return project


def validate_publication(project: Project):
    required = (
        "title",
        "slug",
        "category_id",
        "project_date",
        "short_description",
        "description",
        "location",
    )
    missing = [field for field in required if not getattr(project, field)]
    if missing:
        raise HTTPException(
            422, {"message": "Complete the required fields before publishing", "fields": missing}
        )


def list_projects(db: Session, *, status, category_id, year, page, page_size, q: str | None = None):
    conditions = []
    if q and q.strip():
        # Buscar el texto tal cual: % y _ no deben actuar como comodines.
        conditions.append(Project.title.icontains(q.strip(), autoescape=True))
    if status is not None:
        conditions.append(Project.status == status)
    if category_id is not None:
        conditions.append(Project.category_id == category_id)
    if year is not None:
        conditions.extend(
            [Project.project_date >= date(year, 1, 1), Project.project_date < date(year + 1, 1, 1)]
        )
    total = db.scalar(select(func.count()).select_from(Project).where(*conditions))
    items = db.scalars(
        select(Project)
        .where(*conditions)
        .order_by(Project.project_date.desc().nulls_last(), Project.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def dashboard(db: Session):
    counts = dict(db.execute(select(Project.status, func.count()).group_by(Project.status)).all())
    # El ID mantiene el orden si dos proyectos tienen la misma fecha de edición.
    recent = db.scalars(
        select(Project).order_by(Project.updated_at.desc(), Project.id.desc()).limit(5)
    ).all()
    return {
        "total": sum(counts.values()),
        "draft": counts.get("draft", 0),
        "published": counts.get("published", 0),
        "archived": counts.get("archived", 0),
        "recent": recent,
    }
