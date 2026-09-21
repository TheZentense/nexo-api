import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.modules.volunteering.models import VolunteerApplication
from tests.helpers import login

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL required")
PUBLIC = "/api/v1/volunteer-applications"
ADMIN = "/api/v1/admin/volunteer-applications"


def payload(**changes):
    return {"name": " Ana ", "email": f"{uuid4().hex}@EXAMPLE.COM", "area": "education", **changes}


def submit(account, **changes):
    client, engine, *_ = account
    data = payload(**changes)
    response = client.post(PUBLIC, json=data)
    assert response.status_code == 201
    assert response.json() == {"detail": "Application received"}
    assert response.headers["cache-control"] == "no-store"
    with engine.connect() as db:
        row = (
            db.execute(
                select(VolunteerApplication).where(
                    VolunteerApplication.email == data["email"].lower()
                )
            )
            .mappings()
            .one()
        )
    return dict(row)


@pytest.mark.parametrize("area", ["education", "health", "environment"])
def test_public_submission_preserves_private_data(account, area):
    client, *_ = account
    row = submit(account, area=area)
    assert row["name"] == "Ana"
    assert row["email"] == row["email"].lower()
    assert row["message"] == ""
    assert row["status"] == "pending" and row["version"] == 1
    assert client.get(PUBLIC).status_code == 405
    assert client.get(f"{PUBLIC}/{row['id']}").status_code == 404
    assert client.get(ADMIN).status_code == 401
    assert client.get(f"{ADMIN}/{row['id']}").status_code == 401
    assert (
        client.patch(
            f"{ADMIN}/{row['id']}/status", json={"status": "accepted", "version": 1}
        ).status_code
        == 401
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"name": " "},
        {"name": "x" * 121},
        {"email": "invalid"},
        {"area": "unknown"},
        {"message": "x" * 2001},
        {"status": "accepted"},
        {"version": 8},
    ],
)
def test_invalid_application_is_not_saved(account, changes):
    client, engine, *_ = account
    with engine.connect() as db:
        before = db.execute(text("SELECT count(*) FROM volunteer_applications")).scalar_one()
    response = client.post(PUBLIC, json=payload(**changes))
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    with engine.connect() as db:
        assert (
            db.execute(text("SELECT count(*) FROM volunteer_applications")).scalar_one() == before
        )


def test_submission_limits_share_normalized_email(account):
    client, engine, *_ = account
    data = payload()
    for _ in range(3):
        assert client.post(PUBLIC, json=data).status_code == 201
    data["email"] = data["email"].lower()
    response = client.post(PUBLIC, json=data)
    assert response.status_code == 429 and response.headers["retry-after"] == "900"
    with engine.connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM volunteer_applications WHERE email=:email"),
                {"email": data["email"]},
            ).scalar_one()
            == 3
        )


def test_ip_limit_is_independent_from_contact(account):
    client, *_ = account
    for _ in range(5):
        assert client.post(PUBLIC, json=payload()).status_code == 201
    assert (
        client.post(PUBLIC, json=payload(), headers={"X-Forwarded-For": "192.0.2.1"}).status_code
        == 429
    )
    assert (
        client.post(
            "/api/v1/contact-messages",
            json={"name": "Ana", "email": f"{uuid4().hex}@example.com", "message": "Hello"},
        ).status_code
        == 201
    )


def test_status_changes_filters_conflicts_and_audit(account):
    client, engine, user_id, *_ = account
    row = submit(account, area="health", message="<strong>Keep as text</strong>")
    identifier = str(row["id"])
    login(account)
    detail = client.get(f"{ADMIN}/{identifier}")
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["message"] == row["message"]
    url = f"{ADMIN}/{identifier}/status"
    accepted = client.patch(url, json={"status": "accepted", "version": 1})
    assert accepted.status_code == 200
    assert accepted.headers["cache-control"] == "no-store"
    after = accepted.json()
    assert after["version"] == 2 and after["status"] == "accepted"
    assert after["message"] == row["message"] and after["email"] == row["email"]
    assert client.patch(url, json={"status": "rejected", "version": 1}).status_code == 409
    assert client.patch(url, json={"status": "accepted", "version": 2}).json() == after
    listed = client.get(ADMIN, params={"status": "accepted", "area": "health", "page_size": 1})
    assert listed.headers["cache-control"] == "no-store"
    assert listed.json()["total"] == 1
    assert listed.json()["items"][0]["id"] == identifier
    assert "message" not in listed.json()["items"][0]
    assert (
        client.get(
            ADMIN, params={"status": "accepted", "area": "health", "page": 2, "page_size": 1}
        ).json()["items"]
        == []
    )
    rejected = client.patch(url, json={"status": "rejected", "version": 2}).json()
    assert rejected["version"] == 3
    assert client.get(ADMIN, params={"status": "accepted", "area": "health"}).json()["total"] == 0
    with engine.connect() as db:
        events = (
            db.execute(
                text(
                    "SELECT actor_id,request_id,action,before_data,after_data FROM audit.events WHERE record_id=:id ORDER BY id"
                ),
                {"id": identifier},
            )
            .mappings()
            .all()
        )
        assert len(events) == 2
        assert [event["after_data"]["status"] for event in events] == ["accepted", "rejected"]
        assert events[0]["before_data"]["status"] == "pending"
        assert all(event["actor_id"] == user_id and event["request_id"] for event in events)
        assert all(
            set(event["after_data"]) == {"id", "status", "version", "updated_at"}
            for event in events
        )
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get(ADMIN).status_code == 401
    assert client.patch(url, json={"status": "pending", "version": 3}).status_code == 401


def test_admin_rejects_invalid_filters_and_unknown_ids(account):
    client, *_ = account
    login(account)
    for params in ({"page": 0}, {"page_size": 51}, {"status": "invalid"}, {"area": "invalid"}):
        assert client.get(ADMIN, params=params).status_code == 422
    identifier = uuid4()
    assert client.get(f"{ADMIN}/{identifier}").status_code == 404
    assert (
        client.patch(
            f"{ADMIN}/{identifier}/status", json={"status": "accepted", "version": 1}
        ).status_code
        == 404
    )
    row = submit(account)
    url = f"{ADMIN}/{row['id']}/status"
    for body in (
        {"status": "invalid", "version": 1},
        {"status": "accepted", "version": 0},
        {"status": "accepted", "version": 1, "name": "Changed"},
    ):
        assert client.patch(url, json=body).status_code == 422


def test_restricted_database_role_can_update_status_but_not_history(migrated_database):
    from sqlalchemy.exc import DBAPIError

    engine, *_ = migrated_database
    role = "nexo_volunteer_test_" + uuid4().hex
    identifier = uuid4()
    with engine.connect() as db:
        transaction = db.begin()
        try:
            db.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            db.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            db.execute(text(f'GRANT SELECT,INSERT ON volunteer_applications TO "{role}"'))
            db.execute(
                text(
                    f'GRANT UPDATE(status,version,updated_at) ON volunteer_applications TO "{role}"'
                )
            )
            db.execute(text(f'SET LOCAL ROLE "{role}"'))
            db.execute(
                text(
                    "INSERT INTO volunteer_applications(id,name,email,area) VALUES (:id,'Example','example@example.com','education') RETURNING created_at,version"
                ),
                {"id": identifier},
            ).one()
            db.execute(
                text(
                    "UPDATE volunteer_applications SET status='accepted',version=2,updated_at=now() WHERE id=:id"
                ),
                {"id": identifier},
            )
            for statement in (
                "DELETE FROM audit.events",
                "UPDATE volunteer_applications SET email='changed@example.com'",
                "DELETE FROM volunteer_applications",
                "ALTER TABLE volunteer_applications DISABLE TRIGGER audit_volunteer_status",
            ):
                with pytest.raises(DBAPIError), db.begin_nested():
                    db.execute(text(statement))
            db.execute(text("RESET ROLE"))
            event = db.execute(
                text("SELECT after_data FROM audit.events WHERE record_id=:id"), {"id": identifier}
            ).scalar_one()
            assert event["status"] == "accepted"
        finally:
            transaction.rollback()
