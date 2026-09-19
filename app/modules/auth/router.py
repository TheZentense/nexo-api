from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import set_audit_context
from app.modules.auth.models import AdminUser
from app.modules.auth.schemas import LoginInput
from app.modules.auth.security import DUMMY_HASH, password_hasher, verify_password
from app.modules.auth.service import bearer, create_session, rate_limit, require_admin

router = APIRouter()


def database(request: Request):
    with Session(request.app.state.engine) as db:
        yield db


def no_cache(response: Response):
    response.headers["Cache-Control"] = "no-store"


@router.post("/login")
def login(
    data: LoginInput,
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(database)],
):
    no_cache(response)
    rate_limit(db, "login-ip:" + request.client.host, 30)
    rate_limit(db, "login-email:" + data.email, 5)
    user = db.scalar(select(AdminUser).where(AdminUser.email == data.email).with_for_update())
    valid = verify_password(
        user.password_hash if user else DUMMY_HASH, data.password.get_secret_value()
    )
    if not valid or user is None or not user.is_active:
        raise HTTPException(401, "Invalid credentials")
    if password_hasher.check_needs_rehash(user.password_hash):
        set_audit_context(db, user.id)
        user.password_hash = password_hasher.hash(data.password.get_secret_value())
    token = create_session(db, request, user.id)
    return {
        "admin": {"id": str(user.id), "email": user.email},
        "access_token": token,
        "token_type": "bearer",
        "expires_in": request.app.state.settings.jwt_access_minutes * 60,
    }


@router.get("/me", dependencies=[Depends(bearer)])
def me(request: Request, response: Response, db: Annotated[Session, Depends(database)]):
    no_cache(response)
    user, _ = require_admin(db, request)
    return {"id": str(user.id), "email": user.email}


@router.post("/logout", status_code=204, dependencies=[Depends(bearer)])
def logout(
    request: Request,
    response: Response,
    db: Annotated[Session, Depends(database)],
):
    no_cache(response)
    _, session = require_admin(db, request)
    db.delete(session)
    db.commit()
