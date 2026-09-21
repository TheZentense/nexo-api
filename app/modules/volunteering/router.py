from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.router import database
from app.modules.auth.service import rate_limit
from app.modules.projects.router import AdminDB
from app.modules.volunteering.models import VolunteerApplication
from app.modules.volunteering.schemas import (
    ApplicationDetail,
    ApplicationInput,
    ApplicationPage,
    Area,
    Status,
    StatusInput,
)

public = APIRouter()
admin = APIRouter()


@public.post("/volunteer-applications", status_code=201)
def submit(
    data: ApplicationInput,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(database)],
):
    response.headers["Cache-Control"] = "no-store"
    host = request.client.host if request.client else "unknown"
    rate_limit(db, "volunteer-ip:" + host, 5)
    rate_limit(db, "volunteer-email:" + data.email, 3)
    db.add(VolunteerApplication(**data.model_dump()))
    db.commit()
    return {"detail": "Application received"}


@admin.get("/volunteer-applications", response_model=ApplicationPage)
def list_applications(
    db: AdminDB,
    status: Status | None = None,
    area: Area | None = None,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    conditions = []
    if status is not None:
        conditions.append(VolunteerApplication.status == status)
    if area is not None:
        conditions.append(VolunteerApplication.area == area)
    total = db.scalar(select(func.count()).select_from(VolunteerApplication).where(*conditions))
    items = db.scalars(
        select(VolunteerApplication)
        .where(*conditions)
        .order_by(VolunteerApplication.created_at.desc(), VolunteerApplication.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@admin.get("/volunteer-applications/{application_id}", response_model=ApplicationDetail)
def application_detail(application_id: UUID, db: AdminDB):
    item = db.get(VolunteerApplication, application_id)
    if item is None:
        raise HTTPException(404, "Volunteer application not found")
    return item


@admin.patch("/volunteer-applications/{application_id}/status", response_model=ApplicationDetail)
def change_status(application_id: UUID, data: StatusInput, db: AdminDB):
    item = db.scalar(
        select(VolunteerApplication)
        .where(VolunteerApplication.id == application_id)
        .with_for_update()
    )
    if item is None:
        raise HTTPException(404, "Volunteer application not found")
    if item.version != data.version:
        raise HTTPException(409, "Application changed; reload before updating")
    # La versión evita sobrescribir una decisión tomada desde otra sesión.
    if item.status != data.status:
        item.status = data.status
        item.version += 1
        item.updated_at = datetime.now(UTC)
        db.commit()
    return item
