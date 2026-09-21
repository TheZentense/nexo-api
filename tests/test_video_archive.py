from uuid import uuid4

from sqlalchemy import text

from app.modules.media.worker import process_one
from tests import test_media
from tests.test_media import upload

media = test_media.media
clip = test_media.clip
pytestmark = test_media.pytestmark


def retire(client, identifier, version):
    return client.post(f"/api/v1/admin/videos/{identifier}/archive", json={"version": version})


def test_archive_preserves_private_files_and_audit(media, clip):
    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]
    assert process_one(engine, client.app.state.settings, storage)
    assert (
        client.post(
            f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 1}
        ).status_code
        == 200
    )
    public = f"/api/v1/videos/{identifier}"
    before = client.get(public + "/content").content
    assert client.get(public + "/poster").status_code == 200
    result = retire(client, identifier, 2)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    assert result.json()["status"] == "archived"
    assert result.json()["archived_at"]
    assert client.get(public + "/content").status_code == 404
    assert client.get(public + "/poster").status_code == 404
    assert client.get(f"/api/v1/projects/{project['slug']}/videos?archived=true").json() == []
    listing = f"/api/v1/admin/projects/{project['id']}/videos"
    assert client.get(listing).json() == []
    assert client.get(listing + "?archived=true").json()[0]["id"] == identifier
    assert client.get(f"/api/v1/admin/videos/{identifier}/original").content == clip
    assert client.get(result.json()["video_url"]).content == before
    assert retire(client, identifier, 2).status_code == 409
    assert retire(client, identifier, 3).status_code == 200
    assert client.post(f"/api/v1/admin/videos/{identifier}/retry").status_code == 409
    with engine.connect() as db:
        events = (
            db.execute(
                text(
                    "SELECT actor_id,before_data,after_data FROM audit.events WHERE record_id=:id AND action='archived'"
                ),
                {"id": identifier},
            )
            .mappings()
            .all()
        )
        assert len(events) == 1
        assert events[0]["actor_id"] is not None
        assert events[0]["before_data"]["archived_at"] is None
        assert events[0]["after_data"]["archived_at"]
        assert (
            db.execute(
                text("SELECT version FROM projects WHERE id=:id"), {"id": project["id"]}
            ).scalar_one()
            == 3
        )
    client.headers.pop("Authorization")
    assert retire(client, identifier, 3).status_code == 401
    assert client.get(f"/api/v1/admin/videos/{identifier}/original").status_code == 401


def test_archive_pending_frees_slot_and_worker_skips_it(media, clip):
    client, engine, project, storage = media
    first = upload(client, project, clip).json()["id"]
    second = upload(client, project, clip).json()["id"]
    assert upload(client, project, clip).status_code == 409
    assert retire(client, str(uuid4()), 1).status_code == 404
    assert retire(client, first, 1).status_code == 200
    assert upload(client, project, clip).status_code == 202
    assert process_one(engine, client.app.state.settings, storage)
    rows = client.get(f"/api/v1/admin/projects/{project['id']}/videos").json()
    assert len(rows) == 2
    assert next(item for item in rows if item["id"] == second)["status"] == "ready"
    assert client.get(f"/api/v1/admin/videos/{first}/original").content == clip


def test_archive_during_conversion_discards_output(media, clip, monkeypatch):
    from app.modules.media import worker

    client, engine, project, storage = media
    identifier = upload(client, project, clip).json()["id"]
    original_run = worker.subprocess.run

    def finish_then_retire(*args, **kwargs):
        result = original_run(*args, **kwargs)
        assert retire(client, identifier, 1).status_code == 200
        return result

    monkeypatch.setattr(worker.subprocess, "run", finish_then_retire)
    assert process_one(engine, client.app.state.settings, storage)
    assert client.get(f"/api/v1/admin/projects/{project['id']}/videos").json() == []
    assert client.get(f"/api/v1/admin/videos/{identifier}/original").content == clip
    assert not list(storage.root.rglob("*.mp4"))
    assert not list(storage.root.rglob("*.jpg"))
    with engine.connect() as db:
        row = db.execute(
            text(
                "SELECT archived_at,attempt_id,video_key,poster_key FROM project_videos WHERE id=:id"
            ),
            {"id": identifier},
        ).one()
        assert row.archived_at is not None
        assert row.attempt_id is None and row.video_key is None and row.poster_key is None
