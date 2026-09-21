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
