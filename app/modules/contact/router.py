from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy.orm import Session

from app.modules.auth.router import database
from app.modules.auth.service import rate_limit
from app.modules.contact.models import ContactMessage
from app.modules.contact.schemas import ContactInput

router = APIRouter()


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
