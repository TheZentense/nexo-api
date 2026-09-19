from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import set_audit_context
from app.modules.auth.router import database
from app.modules.auth.service import bearer, require_admin
from app.modules.projects import service
from app.modules.projects.models import Category, Project
from app.modules.projects.schemas import (
    AdminPage,
    AdminProject,
    CategoryInput,
    CategoryOutput,
    ProjectCreate,
    ProjectDetail,
    ProjectPatch,
    PublicPage,
    Status,
    VersionInput,
)

public = APIRouter()

admin = APIRouter()

DB = Annotated[Session, Depends(database)]


def admin_database(
    request: Request,
    response: Response,
    db: DB,
    credentials: Annotated[object, Depends(bearer)],
):
    user, _ = require_admin(db, request)
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        set_audit_context(db, user.id)
    response.headers["Cache-Control"] = "no-store"

    return db


AdminDB = Annotated[Session, Depends(admin_database)]


@public.get("/categories", response_model=list[CategoryOutput])
def categories(db: DB):
    return db.scalars(select(Category).order_by(Category.name, Category.id)).all()


@public.get("/projects", response_model=PublicPage)
def public_projects(
    db: DB,
    category_id: UUID | None = None,
    year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
):
    return service.list_projects(
        db, status="published", category_id=category_id, year=year, page=page, page_size=page_size
    )


@public.get("/projects/{slug}", response_model=ProjectDetail)
def project_detail(slug: str, db: DB):
    project = db.scalar(select(Project).where(Project.slug == slug, Project.status == "published"))
    if project is None:
        raise HTTPException(404, "Project not found")
    return project


@admin.post("/categories", response_model=CategoryOutput, status_code=201)
def create_category(data: CategoryInput, db: AdminDB):
    category = Category(**data.model_dump())
    db.add(category)
    return service.commit(db, category)


@admin.patch("/categories/{category_id}", response_model=CategoryOutput)
def edit_category(category_id: UUID, data: CategoryInput, db: AdminDB):
    category = db.get(Category, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    category.name, category.slug = data.name, data.slug
    return service.commit(db, category)


@admin.get("/projects", response_model=AdminPage)
def admin_projects(
    db: AdminDB,
    status: Status | None = None,
    q: Annotated[
        str | None, Query(max_length=200, description="Case-insensitive title search")
    ] = None,
    category_id: UUID | None = None,
    year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
):
    return service.list_projects(
        db, status=status, category_id=category_id, year=year, page=page, page_size=page_size, q=q
    )


@admin.post("/projects", response_model=AdminProject, status_code=201)
def create_project(data: ProjectCreate, db: AdminDB):
    service.category_exists(db, data.category_id)
    project = Project(**data.model_dump())
    db.add(project)
    return service.commit(db, project)


@admin.get("/projects/{project_id}", response_model=AdminProject)
def admin_project(project_id: UUID, db: AdminDB):
    return service.get_project(db, project_id)


@admin.patch("/projects/{project_id}", response_model=AdminProject)
def edit_project(project_id: UUID, data: ProjectPatch, db: AdminDB):
    project = service.get_project(db, project_id, data.version)
    changes = data.model_dump(exclude_unset=True, exclude={"version"})
    if "category_id" in changes:
        service.category_exists(db, changes["category_id"])
    for field, value in changes.items():
        setattr(project, field, value)
    if project.status == "published":
        service.validate_publication(project)
    return service.commit(db, project)


def transition(project_id: UUID, data: VersionInput, db: Session, target: str):
    project = service.get_project(db, project_id, data.version)
    if target == "published":
        service.validate_publication(project)
    project.status = target
    return service.commit(db, project)


@admin.post("/projects/{project_id}/publish", response_model=AdminProject)
def publish(project_id: UUID, data: VersionInput, db: AdminDB):
    return transition(project_id, data, db, "published")


@admin.post("/projects/{project_id}/archive", response_model=AdminProject)
def archive(project_id: UUID, data: VersionInput, db: AdminDB):
    return transition(project_id, data, db, "archived")


@admin.post("/projects/{project_id}/draft", response_model=AdminProject)
def draft(project_id: UUID, data: VersionInput, db: AdminDB):
    return transition(project_id, data, db, "draft")
