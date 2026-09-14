from datetime import date
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.projects.models import Category, Project


def categories(db: Session):
    return db.scalars(select(Category).order_by(Category.name, Category.id)).all()


def list_projects(
    db: Session, page: int, page_size: int, category_id: UUID | None, year: int | None
):
    conditions = [Project.status == "published"]
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
        .order_by(Project.project_date.desc().nulls_last(), Project.id)
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


def detail(db: Session, slug: str):
    return db.scalar(select(Project).where(Project.slug == slug, Project.status == "published"))
