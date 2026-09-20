from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Literal
from uuid import UUID, uuid4

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import func, select

from app.modules.media.models import ProjectVideo
from app.modules.media.uploads import receive_file
from app.modules.media.video import InvalidVideo, input_options
from app.modules.projects.models import Project
from app.modules.projects.router import DB, AdminDB

admin = APIRouter()
public = APIRouter()


class VideoOutput(BaseModel):
    id: UUID
    status: Literal["pending", "processing", "ready", "failed", "unavailable"]
    video_url: str | None
    poster_url: str | None


def representation(item, request, private=False):
    storage = request.app.state.storage
    status = item.status
    if status == "ready":
        try:
            available = item.video_key and storage.exists(item.video_key)
        except OSError:
            available = False
        if not available:
            status = "unavailable"
    prefix = "/api/v1/admin" if private else "/api/v1"
    base = f"{prefix}/videos/{item.id}"
    poster = None
    if item.status == "ready" and item.poster_key:
        try:
            if storage.exists(item.poster_key):
                poster = base + "/poster"
        except OSError:
            pass
    return {
        "id": item.id,
        "status": status,
        "video_url": base + "/content" if status == "ready" else None,
        "poster_url": poster,
    }


@admin.post(
    "/projects/{project_id}/videos",
    status_code=202,
    response_model=VideoOutput,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(project_id: UUID, request: Request, db: AdminDB):
    limit = request.app.state.settings.video_max_bytes
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    storage = request.app.state.storage
    with TemporaryDirectory(prefix="nexo-upload-") as temporary:
        source = Path(temporary) / "upload"
        size = await receive_file(
            request,
            source,
            limit=limit,
            content_types={
                "application/octet-stream",
                "video/mp4",
                "video/quicktime",
                "video/webm",
            },
        )
        try:
            input_options(source)
        except InvalidVideo:
            raise HTTPException(422, "Unsupported video content") from None
        # Serializamos las altas del mismo proyecto para respetar el límite.
        db.scalar(select(Project).where(Project.id == project_id).with_for_update())
        count = db.scalar(
            select(func.count())
            .select_from(ProjectVideo)
            .where(ProjectVideo.project_id == project_id)
        )
        if count >= 2:
            raise HTTPException(409, "A project can contain at most two videos")
        identifier = uuid4()
        key = f"originals/{identifier}/source"
        item = ProjectVideo(id=identifier, project_id=project_id, original_key=key, size_bytes=size)
        try:
            storage.put(key, source)
        except OSError:
            raise HTTPException(503, "Media storage unavailable") from None
        try:
            db.add(item)
            db.commit()
        except Exception:
            db.rollback()
            storage.delete(key)
            raise
    return representation(item, request, True)


@admin.get("/projects/{project_id}/videos", response_model=list[VideoOutput])
def admin_list(project_id: UUID, request: Request, db: AdminDB):
    if db.get(Project, project_id) is None:
        raise HTTPException(404, "Project not found")
    items = db.scalars(
        select(ProjectVideo)
        .where(ProjectVideo.project_id == project_id)
        .order_by(ProjectVideo.created_at, ProjectVideo.id)
    ).all()
    return [representation(item, request, True) for item in items]


@public.get("/projects/{slug}/videos", response_model=list[VideoOutput])
def public_list(slug: str, request: Request, response: Response, db: DB):
    response.headers["Cache-Control"] = "no-store"
    project = db.scalar(select(Project).where(Project.slug == slug, Project.status == "published"))
    if project is None:
        raise HTTPException(404, "Project not found")
    items = db.scalars(
        select(ProjectVideo)
        .where(ProjectVideo.project_id == project.id)
        .order_by(ProjectVideo.created_at, ProjectVideo.id)
    ).all()
    return [representation(item, request) for item in items]


@admin.post("/videos/{video_id}/retry", response_model=VideoOutput, status_code=202)
def retry(video_id: UUID, request: Request, db: AdminDB):
    item = db.scalar(select(ProjectVideo).where(ProjectVideo.id == video_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Video not found")
    stale = (
        item.status == "processing"
        and item.started_at is not None
        and item.started_at < datetime.now(UTC) - timedelta(minutes=10)
    )
    if item.status != "failed" and not stale:
        raise HTTPException(409, "Video is not eligible for retry")
    item.status, item.error_code, item.attempt_id, item.started_at = "pending", None, None, None
    db.commit()
    return representation(item, request, True)


def content(video_id, variant, request, db, private=False):
    query = select(ProjectVideo).where(ProjectVideo.id == video_id)
    if not private:
        query = query.join(Project).where(Project.status == "published")
    item = db.scalar(query)
    if item is None or (variant != "original" and item.status != "ready"):
        raise HTTPException(404, "Media unavailable")
    key = {"content": item.video_key, "poster": item.poster_key, "original": item.original_key}[
        variant
    ]
    storage = request.app.state.storage
    try:
        if not key or not storage.exists(key):
            raise HTTPException(404, "Media unavailable")
        mime = {
            "content": "video/mp4",
            "poster": "image/jpeg",
            "original": "application/octet-stream",
        }[variant]
        response = storage.response(key, mime)
        if variant == "original":
            response.headers["Content-Disposition"] = 'attachment; filename="original-video"'
        return response
    except OSError:
        raise HTTPException(503, "Media unavailable") from None


@public.get("/videos/{video_id}/{variant}")
def public_content(video_id: UUID, variant: Literal["content", "poster"], request: Request, db: DB):
    return content(video_id, variant, request, db)


@admin.get("/videos/{video_id}/{variant}")
def admin_content(
    video_id: UUID, variant: Literal["content", "poster", "original"], request: Request, db: AdminDB
):
    return content(video_id, variant, request, db, True)
