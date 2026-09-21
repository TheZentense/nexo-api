import os
from uuid import uuid4

import pytest
from sqlalchemy import select, text

from app.modules.contact.models import ContactMessage

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL required")


def payload():
    return {
        "name": " Ana ",
        "email": f"{uuid4().hex}@EXAMPLE.COM",
        "message": " Necesito informacion. ",
    }


def test_public_submission_is_private_and_persisted(account):
    client, engine, *_ = account
    data = payload()
    response = client.post("/api/v1/contact-messages", json=data)
    assert response.status_code == 201
    assert response.json() == {"detail": "Message received"}
    assert response.headers["cache-control"] == "no-store"
    with engine.connect() as db:
        row = (
            db.execute(select(ContactMessage).where(ContactMessage.email == data["email"].lower()))
            .mappings()
            .one()
        )
        assert row["name"] == "Ana"
        assert row["message"] == "Necesito informacion."
        assert row["created_at"] is not None
        identifier = row["id"]
    assert client.get("/api/v1/contact-messages").status_code == 405
    assert client.get(f"/api/v1/contact-messages/{identifier}").status_code == 404


@pytest.mark.parametrize(
    "changes",
    [
        {"name": "   "},
        {"name": "x" * 121},
        {"email": "invalid"},
        {"message": "  "},
        {"message": "x" * 5001},
        {"status": "read"},
    ],
)
def test_invalid_messages_are_not_saved(account, changes):
    client, engine, *_ = account
    data = {**payload(), **changes}
    with engine.connect() as db:
        before = db.execute(text("SELECT count(*) FROM contact_messages")).scalar_one()
    response = client.post("/api/v1/contact-messages", json=data)
    assert response.status_code == 422
    assert all("input" not in error for error in response.json()["detail"])
    with engine.connect() as db:
        assert db.execute(text("SELECT count(*) FROM contact_messages")).scalar_one() == before


def test_email_limit_cannot_be_bypassed_with_case(account):
    client, engine, *_ = account
    data = payload()
    for _ in range(3):
        assert client.post("/api/v1/contact-messages", json=data).status_code == 201
    data["email"] = data["email"].lower()
    response = client.post("/api/v1/contact-messages", json=data)
    assert response.status_code == 429
    assert response.headers["retry-after"] == "900"
    with engine.connect() as db:
        assert (
            db.execute(
                text("SELECT count(*) FROM contact_messages WHERE email=:email"),
                {"email": data["email"]},
            ).scalar_one()
            == 3
        )


def test_ip_limit_ignores_forwarded_header(account):
    client, _, *_ = account
    for _ in range(5):
        assert client.post("/api/v1/contact-messages", json=payload()).status_code == 201
    response = client.post(
        "/api/v1/contact-messages", json=payload(), headers={"X-Forwarded-For": "192.0.2.42"}
    )
    assert response.status_code == 429


@pytest.mark.parametrize("path", ["", "/00000000-0000-0000-0000-000000000001"])
def test_contact_admin_requires_valid_token(account, path):
    client, *_ = account
    url = "/api/v1/admin/contact-messages" + path
    assert client.get(url).status_code == 401
    client.headers["Authorization"] = "Bearer invalid"
    assert client.get(url).status_code == 401


def test_contact_admin_pagination_detail_and_logout(account):
    from tests.helpers import login

    client, engine, *_ = account
    data = payload()
    data["message"] = "<strong>Keep as text</strong>"
    assert client.post("/api/v1/contact-messages", json=data).status_code == 201
    with engine.connect() as db:
        identifier = db.execute(
            select(ContactMessage.id).where(ContactMessage.email == data["email"].lower())
        ).scalar_one()
    login(account)
    url = "/api/v1/admin/contact-messages"
    response = client.get(url, params={"page_size": 1})
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    first = response.json()
    assert first["page"] == 1 and first["page_size"] == 1
    assert first["total"] >= 1
    assert first["items"][0]["id"] == str(identifier)
    assert "message" not in first["items"][0]
    detail = client.get(f"{url}/{identifier}")
    assert detail.status_code == 200
    assert detail.headers["cache-control"] == "no-store"
    assert detail.json()["message"] == data["message"]
    assert detail.json()["email"] == data["email"].lower()
    assert client.get(f"{url}/{uuid4()}").status_code == 404
    empty = client.get(url, params={"page": 10000}).json()
    assert empty["items"] == [] and empty["total"] == first["total"]
    for params in ({"page": 0}, {"page_size": 51}, {"page_size": 0}):
        assert client.get(url, params=params).status_code == 422
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get(f"{url}/{identifier}").status_code == 401


def test_contact_admin_stable_order_for_equal_dates(account):
    from datetime import UTC, datetime

    from sqlalchemy.orm import Session

    from tests.helpers import login

    client, engine, *_ = account
    identifiers = sorted([uuid4(), uuid4(), uuid4()], reverse=True)
    with Session(engine) as db, db.begin():
        for identifier in identifiers:
            db.add(
                ContactMessage(
                    id=identifier,
                    name="Example",
                    email="example@example.com",
                    message="Example",
                    created_at=datetime(2099, 1, 1, tzinfo=UTC),
                )
            )
    login(account)
    ids = []
    for page in (1, 2, 3):
        result = client.get(
            "/api/v1/admin/contact-messages", params={"page": page, "page_size": 1}
        ).json()
        ids.append(result["items"][0]["id"])
    assert ids == [str(identifier) for identifier in identifiers]


def test_handle_message_preserves_content_and_audit(account):
    from tests.helpers import login

    client, engine, user_id, *_ = account
    data = payload()
    assert client.post("/api/v1/contact-messages", json=data).status_code == 201
    with engine.connect() as db:
        identifier = db.execute(
            select(ContactMessage.id).where(ContactMessage.email == data["email"].lower())
        ).scalar_one()
    url = f"/api/v1/admin/contact-messages/{identifier}/handle"
    assert client.post(url).status_code == 401
    login(account)
    before = client.get(f"/api/v1/admin/contact-messages/{identifier}").json()
    pending = client.get("/api/v1/admin/contact-messages?handled=false").json()["total"]
    result = client.post(url)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    after = result.json()
    assert after["handled_at"] is not None
    assert {key: value for key, value in after.items() if key != "handled_at"} == {
        key: value for key, value in before.items() if key != "handled_at"
    }
    assert client.post(url).json() == after
    assert client.get("/api/v1/admin/contact-messages?handled=false").json()["total"] == pending - 1
    done = client.get("/api/v1/admin/contact-messages?handled=true").json()
    assert str(identifier) in [item["id"] for item in done["items"]]
    assert all(item["handled_at"] is not None for item in done["items"])
    assert client.get("/api/v1/admin/contact-messages?handled=invalid").status_code == 422
    assert client.post(f"/api/v1/admin/contact-messages/{uuid4()}/handle").status_code == 404
    with engine.connect() as db:
        events = (
            db.execute(
                text(
                    "SELECT actor_id,request_id,action,before_data,after_data FROM audit.events WHERE record_id=:id"
                ),
                {"id": identifier},
            )
            .mappings()
            .all()
        )
        assert len(events) == 1
        event = events[0]
        assert event["actor_id"] == user_id and event["request_id"] is not None
        assert event["action"] == "handled"
        assert event["before_data"]["handled_at"] is None
        assert event["after_data"]["handled_at"] is not None
        assert set(event["after_data"]) == {"id", "handled_at"}
    client.post("/api/v1/auth/logout")
    assert client.post(url).status_code == 401


def test_public_sender_cannot_mark_message_handled(account):
    client, *_ = account
    data = {**payload(), "handled_at": "2026-01-01T00:00:00Z"}
    assert client.post("/api/v1/contact-messages", json=data).status_code == 422
