import io
import os
from uuid import UUID, uuid4

import pytest
from PIL import Image
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.modules.media.models import ProjectImage
from app.modules.media.storage import LocalStorage
from app.modules.media.worker import process_one
from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


@pytest.fixture
def images(account, tmp_path):
    client, engine, *_ = account
    login(account)
    project, _ = new_project(client)
    storage = LocalStorage(tmp_path / "storage")
    client.app.state.storage = storage
    yield client, engine, project, storage
    with engine.begin() as connection:
        connection.execute(
            update(ProjectImage)
            .where(ProjectImage.project_id == UUID(project["id"]))
            .values(status="failed")
        )


def picture():
    buffer = io.BytesIO()
    Image.new("RGB", (1800, 900), "green").save(buffer, "PNG")
    return buffer.getvalue()


def upload(client, project, data=None):
    return client.post(
        f"/api/v1/admin/projects/{project['id']}/images?alt_text=Green+example",
        content=picture() if data is None else data,
        headers={"Content-Type": "application/octet-stream"},
    )


def gallery(client, project):
    response = client.get(f"/api/v1/admin/projects/{project['id']}/images")
    assert response.status_code == 200
    return response.json()


def layout(client, project, ids, cover, version):
    return client.patch(
        f"/api/v1/admin/projects/{project['id']}/images",
        json={"version": version, "image_ids": ids, "cover_image_id": cover},
    )


def test_complete_gallery_cover_original_and_visibility(images):
    client, engine, project, storage = images
    empty = gallery(client, project)
    assert empty == {"project_version": 1, "cover_image_id": None, "items": []}
    response = upload(client, project)
    assert response.status_code == 202 and response.json()["status"] == "pending"
    first = response.json()["id"]
    second = upload(client, project).json()["id"]
    for _ in range(2):
        assert process_one(engine, client.app.state.settings, storage, kind="image")
    current = gallery(client, project)
    assert current["project_version"] == 3
    assert all(item["status"] == "ready" for item in current["items"])
    assert client.get(f"/api/v1/admin/images/{first}/original").content == picture()
    changed = layout(client, project, [second, first], first, current["project_version"])
    assert changed.status_code == 200
    data = changed.json()
    assert data["project_version"] == 4 and data["cover_image_id"] == first
    assert [item["id"] for item in data["items"]] == [second, first]
    assert [item["position"] for item in data["items"]] == [0, 1]
    assert layout(client, project, [first, second], second, 3).status_code == 409
    assert client.get(f"/api/v1/images/{first}/w480").status_code == 404
    assert client.get(f"/api/v1/projects/{project['slug']}/images").status_code == 404
    published = client.post(f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 4})
    assert published.status_code == 200
    token = client.headers.pop("Authorization")
    result = client.get(f"/api/v1/projects/{project['slug']}/images")
    assert result.headers["cache-control"] == "no-store"
    variant = result.json()["items"][0]["variants"][0]
    image = client.get(variant["url"])
    assert image.status_code == 200 and image.headers["content-type"] == "image/webp"
    assert image.headers["cache-control"] == "no-store"
    assert client.get(f"/api/v1/admin/images/{first}/original").status_code == 401
    assert client.get(f"/api/v1/images/{first}/original").status_code == 422
    client.headers["Authorization"] = token
    client.post(f"/api/v1/admin/projects/{project['id']}/archive", json={"version": 5})
    assert client.get(variant["url"]).status_code == 404
    with engine.connect() as connection:
        events = (
            connection.execute(
                text(
                    "SELECT actor_id,after_data FROM audit.events WHERE record_id=:id ORDER BY id"
                ),
                {"id": first},
            )
            .mappings()
            .all()
        )
    assert events[0]["actor_id"] is not None
    assert events[1]["actor_id"] is None
    assert any(event["after_data"]["is_cover"] for event in events)
    assert all(
        "original_key" not in event["after_data"] and "variants" not in event["after_data"]
        for event in events
    )


def test_invalid_upload_and_quota(images):
    client, _, project, storage = images
    assert upload(client, project, b"<svg></svg>").status_code == 422
    assert upload(client, project, b"").status_code == 422
    client.app.state.settings.image_max_bytes = 10
    assert upload(client, project).status_code == 413
    assert upload(client, project, iter([b"abc", b"defghijklm"])).status_code == 413
    assert not storage.root.exists()
    client.app.state.settings.image_max_bytes = 15 * 1024 * 1024
    for _ in range(10):
        assert upload(client, project).status_code == 202
    assert upload(client, project).status_code == 409
    assert len(list(storage.root.rglob("source"))) == 10
    client.headers.pop("Authorization")
    assert upload(client, project).status_code == 401


def test_gallery_rejects_duplicates_missing_foreign_and_unready_cover(images):
    client, _, project, _ = images
    identifier = upload(client, project).json()["id"]
    for ids, cover in [
        ([identifier, identifier], None),
        ([], None),
        ([str(uuid4())], None),
        ([identifier], identifier),
        ([identifier], str(uuid4())),
    ]:
        assert layout(client, project, ids, cover, 2).status_code == 422
    assert gallery(client, project)["project_version"] == 2


def test_corruption_failure_retry_and_text(images):
    client, engine, project, storage = images
    identifier = upload(client, project, b"\x89PNG\r\n\x1a\n" + bytes(20)).json()["id"]
    assert process_one(engine, client.app.state.settings, storage, kind="image")
    result = gallery(client, project)["items"][0]
    assert result["status"] == "failed" and not result["variants"]
    assert not list(storage.root.rglob("*.webp"))
    assert client.post(f"/api/v1/admin/images/{identifier}/retry").status_code == 202
    assert client.post(f"/api/v1/admin/images/{identifier}/retry").status_code == 409
    updated = client.patch(
        f"/api/v1/admin/images/{identifier}", json={"version": 2, "alt_text": "New description"}
    )
    assert updated.status_code == 200 and updated.json()["alt_text"] == "New description"
    assert gallery(client, project)["project_version"] == 3


def test_missing_variants_and_cover_fallback(images):
    client, engine, project, storage = images
    identifier = upload(client, project).json()["id"]
    process_one(engine, client.app.state.settings, storage, kind="image")
    assert layout(client, project, [identifier], identifier, 2).status_code == 200
    client.post(f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 3})
    with Session(engine) as db:
        variants = db.get(ProjectImage, UUID(identifier)).variants
    storage.delete(variants["w480"]["key"])
    assert len(gallery(client, project)["items"][0]["variants"]) == 2
    for info in variants.values():
        storage.delete(info["key"])
    assert gallery(client, project)["items"][0]["status"] == "unavailable"
    assert client.get(f"/api/v1/images/{identifier}/w480").json() == {"detail": "Media unavailable"}


def test_switching_and_clearing_cover(images):
    client, engine, project, storage = images
    first = upload(client, project).json()["id"]
    second = upload(client, project).json()["id"]
    for _ in range(2):
        process_one(engine, client.app.state.settings, storage, kind="image")
    assert layout(client, project, [first, second], first, 3).status_code == 200
    switched = layout(client, project, [first, second], second, 4)
    assert switched.status_code == 200
    assert [item["is_cover"] for item in switched.json()["items"]] == [False, True]
    cleared = layout(client, project, [first, second], None, 5)
    assert cleared.status_code == 200 and cleared.json()["cover_image_id"] is None


def test_failed_variant_storage_removes_partial_outputs(images, monkeypatch):
    client, engine, project, storage = images
    identifier = upload(client, project).json()["id"]
    put = storage.put

    def fail_second(key, source):
        if key.endswith("w960.webp"):
            raise OSError("Unavailable storage")
        put(key, source)

    monkeypatch.setattr(storage, "put", fail_second)
    assert process_one(engine, client.app.state.settings, storage, kind="image")
    result = gallery(client, project)["items"][0]
    assert result["status"] == "failed" and result["variants"] == []
    assert not list(storage.root.rglob("*.webp"))
    assert client.get(f"/api/v1/admin/images/{identifier}/original").content == picture()
