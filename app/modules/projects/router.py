from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from app.modules.projects import service
from app.modules.projects.schemas import CategoryOutput, ProjectDetail, PublicPage

router = APIRouter()


def database(request: Request):
    with Session(request.app.state.engine) as db:
        yield db


DB = Annotated[Session, Depends(database)]


@router.get("/categories", response_model=list[CategoryOutput])
def categories(db: DB):
    return service.categories(db)


@router.get("/projects", response_model=PublicPage)
def projects(
    db: DB,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 12,
    category_id: UUID | None = None,
    year: Annotated[int | None, Query(ge=1900, le=9998)] = None,
):
    return service.list_projects(db, page, page_size, category_id, year)


@router.get("/projects/{slug}", response_model=ProjectDetail)
def project(slug: str, db: DB):
    result = service.detail(db, slug)
    if result is None:
        raise HTTPException(404, "Proyecto no encontrado")
    return result
