from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Query, Request, Response
from sqlalchemy import func, select

from app.modules.media import image_service as service
from app.modules.media.image import has_image_header
from app.modules.media.image_schemas import GalleryInput, GalleryOutput, ImageOutput, ImageTextInput
from app.modules.media.models import ProjectImage
from app.modules.media.uploads import receive_file
from app.modules.projects.models import Project
from app.modules.projects.router import DB, AdminDB
from app.modules.projects.schemas import VersionInput
from app.modules.projects.service import get_project

admin = APIRouter()
public = APIRouter()


@admin.post(
    "/projects/{project_id}/images",
    status_code=202,
    response_model=ImageOutput,
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/octet-stream": {"schema": {"type": "string", "format": "binary"}}
            },
        }
    },
)
async def upload(
    project_id: UUID,
    request: Request,
    db: AdminDB,
    alt_text: Annotated[str, Query(max_length=250)] = "",
):
    get_project(db, project_id)
    with TemporaryDirectory(prefix="nexo-image-") as temporary:
        source = Path(temporary) / "upload"
        size = await receive_file(
            request,
            source,
            limit=request.app.state.settings.image_max_bytes,
            content_types={"application/octet-stream", "image/jpeg", "image/png", "image/webp"},
        )
        if not has_image_header(source):
            raise HTTPException(422, "Unsupported image content")
        item = service.store_upload(
            db, project_id, source, size, alt_text.strip(), request.app.state.storage
        )
    return service.image_output(item, request.app.state.storage, True)


@admin.get("/projects/{project_id}/images", response_model=GalleryOutput)
def admin_gallery(project_id: UUID, request: Request, db: AdminDB, archived: bool = False):
    return service.gallery(
        db, get_project(db, project_id), request.app.state.storage, True, archived
    )


@public.get("/projects/{slug}/images", response_model=GalleryOutput)
def public_gallery(slug: str, request: Request, response: Response, db: DB):
    project = db.scalar(select(Project).where(Project.slug == slug, Project.status == "published"))
    if project is None:
        raise HTTPException(404, "Project not found")
    response.headers["Cache-Control"] = "no-store"
    return service.gallery(db, project, request.app.state.storage)


@admin.patch("/projects/{project_id}/images", response_model=GalleryOutput)
def update_gallery(project_id: UUID, data: GalleryInput, request: Request, db: AdminDB):
    project = service.update_gallery(db, project_id, data, request.app.state.storage)
    return service.gallery(db, project, request.app.state.storage, True)


@admin.patch("/images/{image_id}", response_model=ImageOutput)
def edit_text(image_id: UUID, data: ImageTextInput, request: Request, db: AdminDB):
    item = db.get(ProjectImage, image_id)
    if item is None:
        raise HTTPException(404, "Image not found")
    project = get_project(db, item.project_id, data.version)
    db.refresh(item)
    if item.archived_at is not None:
        raise HTTPException(409, "Archived images cannot be edited")
    item.alt_text = data.alt_text
    project.updated_at = func.now()
    db.commit()
    return service.image_output(item, request.app.state.storage, True)


@admin.post("/images/{image_id}/retry", response_model=ImageOutput, status_code=202)
def retry(image_id: UUID, request: Request, db: AdminDB):
    return service.image_output(service.retry(db, image_id), request.app.state.storage, True)


@admin.post("/images/{image_id}/archive", response_model=GalleryOutput)
def archive(image_id: UUID, data: VersionInput, request: Request, db: AdminDB):
    project = service.archive(db, image_id, data.version)
    return service.gallery(db, project, request.app.state.storage, True)


def content(image_id, variant, request, db, private=False):
    query = select(ProjectImage).where(ProjectImage.id == image_id)
    if not private:
        query = query.join(Project).where(
            Project.status == "published", ProjectImage.archived_at.is_(None)
        )
    item = db.scalar(query)
    if item is None or (variant != "original" and item.status != "ready"):
        raise HTTPException(404, "Media unavailable")
    key = item.original_key if variant == "original" else item.variants.get(variant, {}).get("key")
    storage = request.app.state.storage
    try:
        if not key or not storage.exists(key):
            raise HTTPException(404, "Media unavailable")
        response = storage.response(
            key, "application/octet-stream" if variant == "original" else "image/webp"
        )
        if variant == "original":
            response.headers["Content-Disposition"] = 'attachment; filename="original-image"'
        return response
    except OSError:
        raise HTTPException(503, "Media unavailable") from None


@public.get("/images/{image_id}/{variant}")
def public_content(
    image_id: UUID, variant: Literal["w480", "w960", "w1600"], request: Request, db: DB
):
    return content(image_id, variant, request, db)


@admin.get("/images/{image_id}/{variant}")
def admin_content(
    image_id: UUID,
    variant: Literal["w480", "w960", "w1600", "original"],
    request: Request,
    db: AdminDB,
):
    return content(image_id, variant, request, db, True)
