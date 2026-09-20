import argparse
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
from app.modules.media.models import ProjectVideo
from app.modules.media.storage import LocalStorage, Storage
from app.modules.projects import models as project_models  # noqa: F401


def process_one(engine, settings: Settings, storage: Storage):
    with Session(engine) as db, db.begin():
        item = db.scalar(
            select(ProjectVideo)
            .where(ProjectVideo.status == "pending")
            .order_by(ProjectVideo.created_at, ProjectVideo.id)
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
                    str(settings.video_max_bytes),
                    str(settings.video_max_seconds),
                ],
                cwd=Path(__file__).resolve().parents[3],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
                timeout=300,
                creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
            )
            storage.put(video_key, root / "web" / "web720.mp4")
            storage.put(poster_key, root / "web" / "poster.jpg")
    except (OSError, subprocess.SubprocessError, ValueError):
        error = "processing_failed"
    retained = False
    try:
        with Session(engine) as db, db.begin():
            item = db.scalar(
                select(ProjectVideo).where(ProjectVideo.id == identifier).with_for_update()
            )
            # Un intento viejo nunca puede reemplazar el resultado de un reintento.
            if item and item.status == "processing" and item.attempt_id == attempt:
                set_audit_context(db, None)
                item.status = "failed" if error else "ready"
                item.error_code = error
                item.video_key = None if error else video_key
                item.poster_key = None if error else poster_key
                retained = not error
    except Exception:
        retained = False
        raise
    finally:
        if not retained:
            storage.delete(video_key)
            storage.delete(poster_key)
    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true", help="Process at most one pending video")
    args = parser.parse_args()
    settings = Settings()
    engine = build_engine(settings)
    storage = LocalStorage(settings.storage_root)
    try:
        while True:
            processed = process_one(engine, settings, storage)
            if args.once:
                break
            if not processed:
                time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
