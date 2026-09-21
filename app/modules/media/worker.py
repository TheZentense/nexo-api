import argparse
import json
import os
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.audit import set_audit_context
from app.core.config import Settings
from app.core.database import build_engine
from app.modules.media.models import ProjectImage, ProjectVideo
from app.modules.media.storage import LocalStorage, Storage
from app.modules.projects import models as project_models  # noqa: F401


def process_one(engine, settings: Settings, storage: Storage, *, kind="video"):
    model = ProjectImage if kind == "image" else ProjectVideo
    conditions = [model.status == "pending"]
    if kind == "image":
        conditions.append(ProjectImage.archived_at.is_(None))
    with Session(engine) as db, db.begin():
        item = db.scalar(
            select(model)
            .where(*conditions)
            .order_by(model.created_at, model.id)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if item is None:
            return False
        item.status = "processing"
        item.started_at = datetime.now(UTC)
        item.attempt_id = uuid4()
        identifier, attempt, original = item.id, item.attempt_id, item.original_key
        set_audit_context(db, None)
    video_key = f"variants/{identifier}/{attempt}/web720.mp4"
    poster_key = f"variants/{identifier}/{attempt}/poster.jpg"
    error = None
    variants = {}
    output_keys = []
    try:
        with TemporaryDirectory(prefix="nexo-convert-") as temporary:
            root = Path(temporary)
            source = root / "original"
            storage.download(original, source)
            # El conversor no necesita JWT, conexión a PostgreSQL ni credenciales del bucket.
            environment = {
                key: value
                for key, value in os.environ.items()
                if key.upper() in {"SYSTEMROOT", "WINDIR", "PATH", "TEMP", "TMP"}
            }
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "app.modules.media.processor",
                    str(source),
                    str(root / "web"),
                    str(settings.image_max_bytes if kind == "image" else settings.video_max_bytes),
                    str(
                        settings.image_max_pixels if kind == "image" else settings.video_max_seconds
                    ),
                    kind,
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            if kind == "image":
                metadata = json.loads((root / "web" / "manifest.json").read_text(encoding="utf-8"))
                if not isinstance(metadata, dict) or not 1 <= len(metadata) <= 3:
                    raise ValueError("Invalid image manifest")
                for label, info in metadata.items():
                    if label not in {"w480", "w960", "w1600"}:
                        raise ValueError("Invalid image variant")
                    width, height = info["width"], info["height"]
                    if not (
                        type(width) is int
                        and type(height) is int
                        and 1 <= width <= 1600
                        and 1 <= height <= 1600
                    ):
                        raise ValueError("Invalid image dimensions")
                    key = f"variants/{identifier}/{attempt}/{label}.webp"
                    output_keys.append(key)
                    output = root / "web" / f"{label}.webp"
                    storage.put(key, output)
                    variants[label] = {
                        "key": key,
                        "width": width,
                        "height": height,
                        "size_bytes": output.stat().st_size,
                    }
            else:
                output_keys.extend([video_key, poster_key])
                storage.put(video_key, root / "web" / "web720.mp4")
                storage.put(poster_key, root / "web" / "poster.jpg")
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError):
        error = "processing_failed"
    retained = False
    try:
        with Session(engine) as db, db.begin():
            item = db.scalar(select(model).where(model.id == identifier).with_for_update())
            # Un intento viejo nunca puede reemplazar el resultado de un reintento.
            if (
                item
                and item.status == "processing"
                and item.attempt_id == attempt
                and (kind != "image" or item.archived_at is None)
            ):
                set_audit_context(db, None)
                item.status = "failed" if error else "ready"
                item.error_code = error
                if kind == "image":
                    item.variants = {} if error else variants
                else:
                    item.video_key = None if error else video_key
                    item.poster_key = None if error else poster_key
                retained = not error
    except Exception:
        retained = False
        raise
    finally:
        if not retained:
            for key in output_keys:
                storage.delete(key)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--once", action="store_true", help="Process at most one pending media file"
    )
    args = parser.parse_args()
    settings = Settings()
    engine = build_engine(settings)
    storage = LocalStorage(settings.storage_root)
    try:
        while True:
            processed = process_one(engine, settings, storage)
            if args.once:
                if not processed:
                    process_one(engine, settings, storage, kind="image")
                break
            processed_image = process_one(engine, settings, storage, kind="image")
            processed = processed or processed_image
            if not processed:
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
