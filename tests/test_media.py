import hashlib
import os
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.orm import Session

from app.modules.media.models import ProjectVideo
from app.modules.media.storage import LocalStorage
from app.modules.media.video import run
from app.modules.media.worker import process_one
from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


@pytest.fixture
def media(account, tmp_path):
    client, engine, *_ = account
    client.app.state.storage = LocalStorage(tmp_path / "storage")
    login(account)
    project, _ = new_project(client)
    yield client, engine, project, client.app.state.storage
    # No dejamos trabajos pendientes que otro caso pueda recoger.
    with engine.begin() as connection:
        connection.execute(
            update(ProjectVideo)
            .where(ProjectVideo.project_id == UUID(project["id"]))
            .values(status="failed")
        )


@pytest.fixture(scope="module")
def clip(tmp_path_factory):
    source = tmp_path_factory.mktemp("video") / "sample.mp4"
    run(
        [
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=160x90:rate=10",
            "-t",
            "0.5",
            "-c:v",
            "libx264",
            "-threads",
            "1",
            str(source),
        ]
    )
    return source.read_bytes()


def upload(client, project, data):
    return client.post(
        f"/api/v1/admin/projects/{project['id']}/videos",
        content=data,
        headers={"Content-Type": "application/octet-stream"},
    )


def test_full_flow_permissions_original_and_audit(media, clip):
    client, engine, project, storage = media
    response = upload(client, project, clip)
    assert response.status_code == 202
    item = response.json()
    identifier = item["id"]
    assert item == {
        "id": identifier,
        "status": "pending",
        "archived_at": None,
        "video_url": None,
        "poster_url": None,
    }
    assert response.headers["cache-control"] == "no-store"
    assert process_one(engine, client.app.state.settings, storage)
    listed = client.get(f"/api/v1/admin/projects/{project['id']}/videos").json()[0]
    assert listed["status"] == "ready"
    assert client.get(listed["video_url"]).headers["content-type"] == "video/mp4"
    assert client.get(listed["poster_url"]).headers["content-type"] == "image/jpeg"
    original = client.get(f"/api/v1/admin/videos/{identifier}/original")
    assert hashlib.sha256(original.content).digest() == hashlib.sha256(clip).digest()
    assert original.headers["content-disposition"].startswith("attachment")
    token = client.headers.pop("Authorization")
    assert client.get(listed["video_url"]).status_code == 401
    assert client.get(f"/api/v1/videos/{identifier}/content").status_code == 404
    assert client.get(f"/api/v1/projects/{project['slug']}/videos").status_code == 404
    client.headers["Authorization"] = token
    assert (
        client.post(
            f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 1}
        ).status_code
        == 200
    )
    client.headers.pop("Authorization")
    public = client.get(f"/api/v1/projects/{project['slug']}/videos")
    assert public.headers["cache-control"] == "no-store"
    assert public.json()[0]["status"] == "ready"
    video = client.get(public.json()[0]["video_url"], headers={"Range": "bytes=0-99"})
    assert video.status_code == 206 and len(video.content) == 100
    assert video.headers["cache-control"] == "no-store"
    assert client.get(f"/api/v1/videos/{identifier}/original").status_code == 422
    client.headers["Authorization"] = token
    client.post(f"/api/v1/admin/projects/{project['id']}/archive", json={"version": 2})
    assert client.get(f"/api/v1/videos/{identifier}/content").status_code == 404
    with engine.connect() as connection:
        events = (
            connection.execute(
                text(
                    "SELECT actor_id,after_data FROM audit.events WHERE record_id=:id ORDER BY id"
                ),
                {"id": identifier},
            )
            .mappings()
            .all()
        )
    assert [event["after_data"]["status"] for event in events] == ["pending", "processing", "ready"]
    assert events[0]["actor_id"] is not None and events[1]["actor_id"] is None
    assert all("original_key" not in event["after_data"] for event in events)


def test_invalid_oversized_and_anonymous_uploads(media, clip):
    client, _, project, storage = media
    assert upload(client, project, b"fake mp4").status_code == 422
    assert upload(client, project, b"").status_code == 422
    client.app.state.settings.video_max_bytes = 10
    assert upload(client, project, clip).status_code == 413
    assert upload(client, project, iter([clip[:8], clip[8:]])).status_code == 413
    client.headers.pop("Authorization")
    assert upload(client, project, clip).status_code == 401
    assert not storage.root.exists()


def test_quota_and_unknown_project(media, clip):
    client, _, project, storage = media
    assert upload(client, {"id": str(uuid4())}, clip).status_code == 404
    assert upload(client, project, clip).status_code == 202
    assert upload(client, project, clip).status_code == 202
    assert upload(client, project, clip).status_code == 409
    assert len(list(storage.root.rglob("source"))) == 2


def test_corrupt_video_failure_and_retry(media):
    client, engine, project, storage = media
    identifier = upload(client, project, b"\x00\x00\x00\x18ftypisom" + bytes(100)).json()["id"]
    assert process_one(engine, client.app.state.settings, storage)
    result = client.get(f"/api/v1/admin/projects/{project['id']}/videos").json()[0]
    assert result["status"] == "failed" and result["video_url"] is None
    assert client.get(f"/api/v1/admin/videos/{identifier}/content").status_code == 404
    assert len(list(storage.root.rglob("source"))) == 1
    assert not list(storage.root.rglob("*.mp4"))
    assert client.post(f"/api/v1/admin/videos/{identifier}/retry").status_code == 202
    assert client.post(f"/api/v1/admin/videos/{identifier}/retry").status_code == 409


def test_missing_optimized_file_is_unavailable(media, clip):
    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]
    process_one(engine, client.app.state.settings, storage)
    with Session(engine) as db:
        key = db.get(ProjectVideo, UUID(identifier)).video_key
    storage.delete(key)
    result = client.get(f"/api/v1/admin/projects/{project['id']}/videos").json()[0]
    assert result["status"] == "unavailable" and result["video_url"] is None
    assert client.get(result["poster_url"]).status_code == 200
    assert client.get(f"/api/v1/admin/videos/{identifier}/content").json() == {
        "detail": "Media unavailable"
    }


def test_worker_timeout_preserves_original(media, clip, monkeypatch):
    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]

    def timeout(*args, **kwargs):
        assert "DATABASE_URL" not in kwargs["env"] and "JWT_SECRET" not in kwargs["env"]
        raise subprocess.TimeoutExpired("processor", 300)

    monkeypatch.setattr("app.modules.media.worker.subprocess.run", timeout)
    assert process_one(engine, client.app.state.settings, storage)
    with Session(engine) as db:
        item = db.get(ProjectVideo, UUID(identifier))
        assert item.status == "failed"
        assert storage.path(item.original_key).read_bytes() == clip


def test_retry_recovers_interrupted_job(media, clip):
    client, engine, project, _ = media
    identifier = upload(client, project, clip).json()["id"]
    with engine.begin() as connection:
        connection.execute(
            update(ProjectVideo)
            .where(ProjectVideo.id == UUID(identifier))
            .values(status="processing", started_at=datetime.now(UTC), attempt_id=uuid4())
        )
    assert client.post(f"/api/v1/admin/videos/{identifier}/retry").status_code == 409
    with engine.begin() as connection:
        connection.execute(
            update(ProjectVideo)
            .where(ProjectVideo.id == UUID(identifier))
            .values(started_at=datetime.now(UTC) - timedelta(minutes=11))
        )
    assert client.post(f"/api/v1/admin/videos/{identifier}/retry").json()["status"] == "pending"


def test_worker_skips_locked_jobs(media, clip):
    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]
    with Session(engine) as db, db.begin():
        db.scalar(select(ProjectVideo).where(ProjectVideo.id == UUID(identifier)).with_for_update())
        assert not process_one(engine, client.app.state.settings, storage)


def test_worker_command_in_separate_process(media, clip):
    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]
    environment = os.environ.copy()
    environment["DATABASE_URL"] = engine.url.render_as_string(hide_password=False)
    environment["STORAGE_ROOT"] = str(storage.root)
    result = subprocess.run(
        [sys.executable, "-m", "app.modules.media.worker", "--once"],
        env=environment,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, "Worker command failed"
    with Session(engine) as db:
        assert db.get(ProjectVideo, UUID(identifier)).status == "ready"
