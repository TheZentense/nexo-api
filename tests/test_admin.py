import os
import secrets
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
import pytest
from sqlalchemy import update
from sqlalchemy.orm import Session

from app.modules.auth.models import AdminSession, AdminUser
from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


def test_migration_preserves_existing_data(migrated_database):
    _, _, before, after = migrated_database
    assert before == {key: after[key] for key in before}
    assert after["version"] == 1


def test_login_logout_and_cookie_rejection(account):
    client, _, _, email, _ = account
    assert client.get("/api/v1/auth/me").status_code == 401
    response = login(account)
    assert "set-cookie" not in response.headers
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["expires_in"] == 1800
    assert client.get("/api/v1/auth/me").json()["email"] == email
    client.cookies.set("access_token", response.json()["access_token"])
    assert client.get("/api/v1/auth/me", headers={"Authorization": ""}).status_code == 401
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get("/api/v1/auth/me").status_code == 401


@pytest.mark.parametrize(
    "case",
    [
        "signature",
        "expired",
        "audience",
        "issuer",
        "missing",
        "algorithm",
        "subject",
        "unregistered",
        "future",
    ],
)
def test_invalid_jwt_is_rejected(account, case):
    client, _, _, _, _ = account
    token = login(account).json()["access_token"]
    claims = jwt.decode(token, options={"verify_signature": False})
    key = client.app.state.settings.jwt_secret.get_secret_value()
    algorithm = "HS256"
    if case == "signature":
        key = secrets.token_urlsafe(48)
    elif case == "expired":
        claims["exp"] = 1
    elif case == "audience":
        claims["aud"] = "other"
    elif case == "issuer":
        claims["iss"] = "other"
    elif case == "missing":
        del claims["exp"]
    elif case == "algorithm":
        algorithm = "HS384"
    elif case == "subject":
        claims["sub"] = str(uuid4())
    elif case == "unregistered":
        claims["jti"] = str(uuid4())
    else:
        claims["nbf"] = int(datetime.now(UTC).timestamp()) + 3600
    invalid = jwt.encode(claims, key, algorithm=algorithm)
    response = client.get("/api/v1/auth/me", headers={"Authorization": "Bearer " + invalid})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize("case", ["disabled", "expired"])
def test_revoked_account_or_session(account, case):
    client, engine, user_id, _, _ = account
    login(account)
    with Session(engine) as db, db.begin():
        if case == "disabled":
            db.execute(update(AdminUser).where(AdminUser.id == user_id).values(is_active=False))
        else:
            db.execute(
                update(AdminSession)
                .where(AdminSession.admin_id == user_id)
                .values(expires_at=datetime.now(UTC) - timedelta(seconds=1))
            )
    assert client.get("/api/v1/auth/me").status_code == 401


def test_login_limit(account):
    client, _, _, email, _ = account
    for _ in range(5):
        result = client.post("/api/v1/auth/login", json={"email": email, "password": "incorrect"})
        assert result.status_code == 401
        assert result.json() == {"detail": "Invalid credentials"}
    result = client.post("/api/v1/auth/login", json={"email": email, "password": "incorrect"})
    assert result.status_code == 429
    assert result.headers["retry-after"] == "900"


def test_password_reset_revokes_tokens(account, monkeypatch):
    from scripts import admin

    client, _, _, email, _ = account
    login(account)
    new_password = secrets.token_urlsafe(32)
    monkeypatch.setattr("sys.argv", ["admin", "reset-password", email])
    monkeypatch.setattr(admin, "getpass", lambda _: new_password)
    admin.main()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": email, "password": new_password}
        ).status_code
        == 200
    )


def test_admin_project_lifecycle(account):
    client, _, _, _, _ = account
    assert client.get("/api/v1/admin/projects").status_code == 401
    assert (
        client.post(
            "/api/v1/admin/categories", json={"name": "Denied", "slug": "denied"}
        ).status_code
        == 401
    )
    login(account)
    project, _ = new_project(client)
    route = "/api/v1/admin/projects/" + project["id"]
    public = "/api/v1/projects/" + project["slug"]
    assert project["status"] == "draft" and project["version"] == 1
    assert client.get(public).status_code == 404
    assert client.get(route).status_code == 200
    edited = client.patch(route, json={"version": 1, "progress_percent": 25})
    assert edited.status_code == 200 and edited.json()["version"] == 2
    assert client.patch(route, json={"version": 1, "progress_percent": 50}).status_code == 409
    result = client.post(route + "/publish", json={"version": 2})
    assert result.status_code == 200 and result.json()["version"] == 3
    assert client.get(public).json()["progress_percent"] == 25
    assert client.patch(route, json={"version": 3, "description": " "}).status_code == 422
    assert client.post(route + "/archive", json={"version": 3}).json()["status"] == "archived"
    assert client.get(public).status_code == 404
    assert client.post(route + "/draft", json={"version": 4}).json()["status"] == "draft"
    assert client.get(route).json()["description"] == "Example description"


def test_category_edit_and_conflicts(account):
    client, _, _, _, _ = account
    login(account)
    project, data = new_project(client)
    route = "/api/v1/admin/categories/" + data["category_id"]
    changed = client.patch(
        route, json={"name": "Renamed " + uuid4().hex, "slug": "renamed-" + uuid4().hex}
    )
    assert changed.status_code == 200
    assert (
        client.post(
            "/api/v1/admin/categories",
            json={"name": changed.json()["name"], "slug": changed.json()["slug"]},
        ).status_code
        == 409
    )
    assert client.post("/api/v1/admin/projects", json=data).status_code == 409
    assert (
        client.patch(
            "/api/v1/admin/projects/" + project["id"],
            json={"version": 1, "category_id": str(uuid4())},
        ).status_code
        == 422
    )


@pytest.mark.parametrize(
    "change",
    [
        {"progress_percent": 101},
        {"title": None},
        {"status": "published"},
        {"beneficiaries_count": -1},
        {},
    ],
)
def test_invalid_project_changes(account, change):
    client, _, _, _, _ = account
    login(account)
    project, _ = new_project(client)
    assert (
        client.patch(
            "/api/v1/admin/projects/" + project["id"], json={"version": 1, **change}
        ).status_code
        == 422
    )


def test_incomplete_project_cannot_be_published(account):
    client, _, _, _, _ = account
    login(account)
    project = client.post(
        "/api/v1/admin/projects", json={"title": "Draft", "slug": "draft-" + uuid4().hex}
    ).json()
    assert (
        client.post(
            "/api/v1/admin/projects/" + project["id"] + "/publish", json={"version": 1}
        ).status_code
        == 422
    )


def test_cli_create_and_disable(account, monkeypatch):
    from scripts import admin

    client, _, _, _, _ = account
    email = "cli-" + uuid4().hex + "@example.com"
    password = secrets.token_urlsafe(32)
    monkeypatch.setattr("sys.argv", ["admin", "create", email])
    monkeypatch.setattr(admin, "getpass", lambda _: password)
    admin.main()
    with pytest.raises(SystemExit, match="already exists"):
        admin.main()
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    monkeypatch.setattr("sys.argv", ["admin", "disable", email])
    admin.main()
    assert client.get("/api/v1/auth/me").status_code == 401
    assert (
        client.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code
        == 401
    )
