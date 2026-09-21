from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import Settings
from app.core.database import build_engine
from app.modules.auth.router import router as auth_router
from app.modules.contact.router import router as contact_router
from app.modules.media.image_router import admin as image_admin
from app.modules.media.image_router import public as image_public
from app.modules.media.router import admin as media_admin
from app.modules.media.router import public as media_public
from app.modules.media.storage import LocalStorage
from app.modules.projects.router import admin, public


def create_app(settings: Settings | None = None):
    settings = settings or Settings()
    engine = build_engine(settings)

    @asynccontextmanager
    async def lifespan(app):
        yield
        engine.dispose()

    app = FastAPI(title="Nexo API", version="0.2.0", lifespan=lifespan)
    app.state.engine = engine
    app.state.settings = settings
    app.state.storage = LocalStorage(settings.storage_root)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PATCH"],
        allow_headers=["Content-Type", "Authorization"],
    )
    app.include_router(public, prefix="/api/v1", tags=["Projects"])
    app.include_router(admin, prefix="/api/v1/admin", tags=["Administration"])
    app.include_router(auth_router, prefix="/api/v1/auth", tags=["Authentication"])
    app.include_router(media_admin, prefix="/api/v1/admin", tags=["Videos"])
    app.include_router(media_public, prefix="/api/v1", tags=["Videos"])
    app.include_router(image_admin, prefix="/api/v1/admin", tags=["Images"])
    app.include_router(image_public, prefix="/api/v1", tags=["Images"])

    app.include_router(contact_router, prefix="/api/v1", tags=["Contact"])

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
            headers={**(exc.headers or {}), "Cache-Control": "no-store"},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # No devolver el cuerpo recibido: podría contener la contraseña.
        errors = [
            {key: value for key, value in error.items() if key in {"type", "loc", "msg"}}
            for error in exc.errors()
        ]
        return JSONResponse(
            status_code=422,
            content=jsonable_encoder({"detail": errors}),
            headers={"Cache-Control": "no-store"},
        )

    @app.exception_handler(SQLAlchemyError)
    async def database_error(request, exc):
        return JSONResponse(
            status_code=503,
            content={"detail": "Database unavailable"},
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/v1/health/live", tags=["Health"])
    def live():
        return {"status": "ok"}

    @app.get("/api/v1/health/ready", tags=["Health"])
    def ready():
        with app.state.engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return {"status": "ok", "database": "reachable"}

    return app
