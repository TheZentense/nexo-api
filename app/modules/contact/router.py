from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.auth.router import database
from app.modules.auth.service import rate_limit
from app.modules.contact.models import ContactMessage
from app.modules.contact.schemas import ContactDetail, ContactInput, ContactPage
from app.modules.projects.router import AdminDB

router = APIRouter()
admin = APIRouter()


@router.post("/contact-messages", status_code=201)
def submit(
    data: ContactInput,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(database)],
):
    response.headers["Cache-Control"] = "no-store"
    # Compartimos el contador existente; contacto tiene sus propias claves.
    host = request.client.host if request.client else "unknown"
    rate_limit(db, "contact-ip:" + host, 5)
    rate_limit(db, "contact-email:" + data.email, 3)
    db.add(ContactMessage(**data.model_dump()))
    db.commit()
    return {"detail": "Message received"}


@admin.get("/contact-messages", response_model=ContactPage)
def list_messages(
    db: AdminDB,
    page: Annotated[int, Query(ge=1, le=10000)] = 1,
    page_size: Annotated[int, Query(ge=1, le=50)] = 20,
):
    total = db.scalar(select(func.count()).select_from(ContactMessage))
    items = db.scalars(
        select(ContactMessage)
        .order_by(ContactMessage.created_at.desc(), ContactMessage.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    return {"items": items, "total": total, "page": page, "page_size": page_size}


@admin.get("/contact-messages/{message_id}", response_model=ContactDetail)
def message_detail(message_id: UUID, db: AdminDB):
    item = db.get(ContactMessage, message_id)
    if item is None:
        raise HTTPException(404, "Contact message not found")
    return item
