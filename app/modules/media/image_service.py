from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.modules.media.models import ProjectImage
from app.modules.media.storage import Storage
from app.modules.projects.models import Project
from app.modules.projects.service import get_project


def available_variants(item, storage: Storage):
    if item.status != "ready":
        return {}
    result = {}
    for label, info in item.variants.items():
        try:
            if storage.exists(info["key"]):
                result[label] = info
        except OSError:
            pass
    return result


def image_output(item, storage: Storage, private=False):
    available = available_variants(item, storage)
    prefix = "/api/v1/admin" if private else "/api/v1"
    return {
        "id": item.id,
        "status": "unavailable" if item.status == "ready" and not available else item.status,
        "position": item.position,
        "is_cover": item.is_cover,
        "alt_text": item.alt_text,
        "variants": [
            {
                "label": label,
                "url": f"{prefix}/images/{item.id}/{label}",
                "width": info["width"],
                "height": info["height"],
                "size_bytes": info["size_bytes"],
            }
            for label, info in available.items()
        ],
    }


def gallery(db: Session, project, storage: Storage, private=False):
    items = db.scalars(
        select(ProjectImage)
        .where(ProjectImage.project_id == project.id)
        .order_by(ProjectImage.position, ProjectImage.id)
    ).all()
    return {
        "project_version": project.version,
        "cover_image_id": next((item.id for item in items if item.is_cover), None),
        "items": [image_output(item, storage, private) for item in items],
    }


def store_upload(db, project_id, source, size, alt_text, storage: Storage):
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise HTTPException(404, "Project not found")
    count = db.scalar(
        select(func.count()).select_from(ProjectImage).where(ProjectImage.project_id == project_id)
    )
    if count >= 10:
        raise HTTPException(409, "A project can contain at most ten images")
    identifier = uuid4()
    key = f"originals/{identifier}/source"
    item = ProjectImage(
        id=identifier,
        project_id=project_id,
        original_key=key,
        size_bytes=size,
        position=count,
        alt_text=alt_text,
    )
    try:
        storage.put(key, source)
    except OSError:
        raise HTTPException(503, "Media storage unavailable") from None
    try:
        db.add(item)
        project.updated_at = func.now()
        db.commit()
    except Exception:
        db.rollback()
        storage.delete(key)
        raise
    return item


def update_gallery(db, project_id, data, storage):
    project = get_project(db, project_id, data.version)
    items = db.scalars(select(ProjectImage).where(ProjectImage.project_id == project_id)).all()
    by_id = {item.id: item for item in items}
    if len(data.image_ids) != len(set(data.image_ids)) or set(data.image_ids) != set(by_id):
        raise HTTPException(422, "Include every image of this project exactly once")
    if data.cover_image_id is not None:
        cover = by_id.get(data.cover_image_id)
        if cover is None or not available_variants(cover, storage):
            raise HTTPException(422, "Choose an available image from this project as cover")
    # Quitamos primero la portada anterior para respetar el índice único.
    for item in items:
        item.is_cover = False
    db.flush()
    for position, identifier in enumerate(data.image_ids):
        by_id[identifier].position = position
        by_id[identifier].is_cover = identifier == data.cover_image_id
    project.updated_at = func.now()
    db.commit()
    return project


def retry(db, image_id):
    item = db.scalar(select(ProjectImage).where(ProjectImage.id == image_id).with_for_update())
    if item is None:
        raise HTTPException(404, "Image not found")
    stale = (
        item.status == "processing"
        and item.started_at is not None
        and item.started_at < datetime.now(UTC) - timedelta(minutes=10)
    )
    if item.status != "failed" and not stale:
        raise HTTPException(409, "Image is not eligible for retry")
    item.status, item.error_code, item.attempt_id, item.started_at = "pending", None, None, None
    db.commit()
    return item


def cover_urls(db: Session, project_ids: list[UUID], storage: Storage):
    if not project_ids:
        return {}
    items = db.scalars(
        select(ProjectImage).where(
            ProjectImage.project_id.in_(project_ids), ProjectImage.is_cover.is_(True)
        )
    ).all()
    result = {}
    for item in items:
        available = available_variants(item, storage)
        if available:
            label = min(available, key=lambda key: available[key]["width"])
            result[item.project_id] = f"/api/v1/images/{item.id}/{label}"
    return result
