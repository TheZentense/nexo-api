from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import jwt
from fastapi import HTTPException, Request
from fastapi.security import HTTPBearer
from sqlalchemy import case, func
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.modules.auth.models import AdminSession, AdminUser, AuthRateLimit
from app.modules.auth.security import digest

bearer = HTTPBearer(auto_error=False, bearerFormat="JWT")


def rate_limit(db: Session, key: str, maximum: int, seconds: int = 900):
    """Cuenta los intentos en PostgreSQL para compartir el límite entre procesos."""
    expiry = datetime.now(UTC) + timedelta(seconds=seconds)
    statement = insert(AuthRateLimit).values(key=digest(key), attempts=1, expires_at=expiry)
    statement = statement.on_conflict_do_update(
        index_elements=[AuthRateLimit.key],
        set_={
            "attempts": case(
                (AuthRateLimit.expires_at <= func.now(), 1), else_=AuthRateLimit.attempts + 1
            ),
            "expires_at": case(
                (AuthRateLimit.expires_at <= func.now(), expiry), else_=AuthRateLimit.expires_at
            ),
        },
    ).returning(AuthRateLimit.attempts)
    count = db.execute(statement).scalar_one()
    db.commit()
    if count > maximum:
        raise HTTPException(
            429, "Too many attempts; try again later", headers={"Retry-After": str(seconds)}
        )


def create_session(db: Session, request: Request, admin_id):
    settings = request.app.state.settings
    now = datetime.now(UTC)
    expires = now + timedelta(minutes=settings.jwt_access_minutes)
    identifier = str(uuid4())
    token = jwt.encode(
        {
            "sub": str(admin_id),
            "jti": identifier,
            "iat": now,
            "nbf": now,
            "exp": expires,
            "iss": settings.jwt_issuer,
            "aud": settings.jwt_audience,
        },
        settings.jwt_secret.get_secret_value(),
        algorithm="HS256",
    )
    db.add(AdminSession(token_hash=digest(identifier), admin_id=admin_id, expires_at=expires))
    db.commit()
    return token


def require_admin(db: Session, request: Request):
    settings = request.app.state.settings
    authorization = request.headers.get("authorization", "").split()
    try:
        if len(authorization) != 2 or authorization[0].lower() != "bearer":
            raise ValueError("Missing bearer")

        claims = jwt.decode(
            authorization[1],
            settings.jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            options={"require": ["sub", "jti", "iat", "nbf", "exp", "iss", "aud"]},
        )

        admin_id = UUID(claims["sub"])

        identifier = str(UUID(claims["jti"]))
    except (jwt.InvalidTokenError, ValueError, TypeError, AttributeError):
        raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"}) from None
    session = db.get(AdminSession, digest(identifier))
    user = db.get(AdminUser, admin_id) if session and session.admin_id == admin_id else None
    if user is None or not user.is_active or session.expires_at <= datetime.now(UTC):
        raise HTTPException(401, "Invalid token", headers={"WWW-Authenticate": "Bearer"})
    return user, session
