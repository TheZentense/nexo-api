from uuid import UUID, uuid4

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.modules.media.models import ProjectImage
from app.modules.media.worker import process_one
from tests import test_images_api
from tests.test_images_api import gallery, layout, picture, upload

images = test_images_api.images
pytestmark = test_images_api.pytestmark


def archived(client, project):
    return client.get(f"/api/v1/admin/projects/{project['id']}/images?archived=true").json()


def test_retire_cover_preserves_files_and_audit(images):
    client, engine, project, storage = images
    first = upload(client, project).json()["id"]
    second = upload(client, project).json()["id"]
    for _ in range(2):
        process_one(engine, client.app.state.settings, storage, kind="image")
    assert layout(client, project, [first, second], first, 3).status_code == 200
    client.post(f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 4})
    public_url = f"/api/v1/images/{first}/w480"
    before = client.get(public_url).content
    response = client.post(f"/api/v1/admin/images/{first}/archive", json={"version": 5})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    result = response.json()
    assert result["project_version"] == 6 and result["cover_image_id"] is None
    assert [item["id"] for item in result["items"]] == [second]
    assert result["items"][0]["position"] == 0
    assert client.get(public_url).status_code == 404
    assert client.get(f"/api/v1/projects/{project['slug']}").json()["cover_url"] is None
    visible = client.get(f"/api/v1/projects/{project['slug']}/images?archived=true").json()
    assert [item["id"] for item in visible["items"]] == [second]
    history = archived(client, project)
    assert history["items"][0]["id"] == first
    assert history["items"][0]["status"] == "archived" and history["items"][0]["archived_at"]
    assert client.get(f"/api/v1/admin/images/{first}/w480").content == before
    assert client.get(f"/api/v1/admin/images/{first}/original").content == picture()
    assert (
        client.post(f"/api/v1/admin/images/{first}/archive", json={"version": 5}).status_code == 409
    )
    repeated = client.post(f"/api/v1/admin/images/{first}/archive", json={"version": 6})
    assert repeated.status_code == 200 and repeated.json()["project_version"] == 6
    with engine.connect() as connection:
        events = (
            connection.execute(
                text("SELECT * FROM audit.events WHERE record_id=:id AND action='archived'"),
                {"id": first},
            )
            .mappings()
            .all()
        )
    assert len(events) == 1 and events[0]["actor_id"] is not None
    assert events[0]["before_data"]["archived_at"] is None
    assert events[0]["after_data"]["archived_at"] is not None


def test_retire_pending_image_frees_slot_and_worker_skips_it(images):
    client, engine, project, storage = images
    identifiers = [upload(client, project).json()["id"] for _ in range(10)]
    assert upload(client, project).status_code == 409
    result = client.post(f"/api/v1/admin/images/{identifiers[0]}/archive", json={"version": 11})
    assert result.status_code == 200
    assert upload(client, project).status_code == 202
    active = gallery(client, project)
    assert len(active["items"]) == 10 and len(archived(client, project)["items"]) == 1
    assert [item["position"] for item in active["items"]] == list(range(10))
    assert len(list(storage.root.rglob("source"))) == 11
    process_one(engine, client.app.state.settings, storage, kind="image")
    with Session(engine) as db:
        assert db.get(ProjectImage, UUID(identifiers[0])).status == "pending"
        assert db.get(ProjectImage, UUID(identifiers[1])).status == "ready"


def test_retiring_during_conversion_cannot_restore_image(images, monkeypatch):
    from app.modules.media import worker

    client, engine, project, storage = images
    identifier = upload(client, project).json()["id"]
    run = worker.subprocess.run

    def retire_before_result(*args, **kwargs):
        result = run(*args, **kwargs)
        response = client.post(f"/api/v1/admin/images/{identifier}/archive", json={"version": 2})
        assert response.status_code == 200
        return result

    monkeypatch.setattr(worker.subprocess, "run", retire_before_result)
    assert process_one(engine, client.app.state.settings, storage, kind="image")
    assert gallery(client, project)["items"] == []
    assert archived(client, project)["items"][0]["status"] == "archived"
    assert not list(storage.root.rglob("*.webp"))
    assert client.get(f"/api/v1/admin/images/{identifier}/original").content == picture()
    with Session(engine) as db:
        item = db.get(ProjectImage, UUID(identifier))
        assert item.archived_at and item.attempt_id is None and item.variants == {}


def test_retired_images_cannot_be_edited_retried_or_selected(images):
    client, _, project, _ = images
    identifier = upload(client, project).json()["id"]
    token = client.headers.pop("Authorization")
    assert (
        client.post(f"/api/v1/admin/images/{identifier}/archive", json={"version": 2}).status_code
        == 401
    )
    client.headers["Authorization"] = token
    assert (
        client.post(f"/api/v1/admin/images/{uuid4()}/archive", json={"version": 2}).status_code
        == 404
    )
    assert (
        client.post(f"/api/v1/admin/images/{identifier}/archive", json={"version": 2}).status_code
        == 200
    )
    assert (
        client.patch(
            f"/api/v1/admin/images/{identifier}", json={"version": 3, "alt_text": "Changed"}
        ).status_code
        == 409
    )
    assert client.post(f"/api/v1/admin/images/{identifier}/retry").status_code == 409
    assert layout(client, project, [identifier], identifier, 3).status_code == 422
    assert gallery(client, project)["project_version"] == 3
