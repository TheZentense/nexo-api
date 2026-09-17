from datetime import date
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.config import Settings
from app.core.database import Base
from app.main import create_app
from app.modules.projects.models import Category, Project


@pytest.fixture
def client():
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/test"))
    original = app.state.engine
    engine = create_engine(
        "sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    Base.metadata.create_all(engine)
    with Session(engine) as db, db.begin():
        category = Category(name="Example", slug="example")
        db.add(category)
        db.flush()
        for state in ["draft", "published", "archived"]:
            db.add(
                Project(
                    title=state,
                    slug=state,
                    category_id=category.id,
                    status=state,
                    project_date=date(2026, 1, 1),
                )
            )
    app.state.engine = engine
    with TestClient(app) as c:
        yield c
    engine.dispose()
    original.dispose()


def test_public_catalog_and_detail(client):
    page = client.get("/api/v1/projects").json()
    assert page["total"] == 1
    assert [p["slug"] for p in page["items"]] == ["published"]
    assert client.get("/api/v1/projects/published").status_code == 200


@pytest.mark.parametrize("slug", ["draft", "archived", "missing"])
def test_nonpublic_detail_returns_404(client, slug):
    assert client.get("/api/v1/projects/" + slug).status_code == 404


def test_filters_and_pagination(client):
    category = client.get("/api/v1/categories").json()[0]["id"]
    assert (
        client.get("/api/v1/projects", params={"category_id": category, "year": 2026}).json()[
            "total"
        ]
        == 1
    )
    for params in [{"category_id": str(uuid4())}, {"year": 2025}]:
        assert client.get("/api/v1/projects", params=params).json()["items"] == []
    page = client.get("/api/v1/projects?page=2&page_size=1").json()
    assert page["total"] == 1 and page["items"] == []


@pytest.mark.parametrize("query", ["page=0", "page_size=51", "year=9999", "category_id=invalid"])
def test_invalid_parameters(client, query):
    assert client.get("/api/v1/projects?" + query).status_code == 422


def test_health_and_read_only(client):
    assert client.get("/api/v1/health/live").json() == {"status": "ok"}
    assert client.get("/api/v1/health/ready").status_code == 200
    assert client.post("/api/v1/projects", json={}).status_code == 405


def test_invalid_configuration():
    with pytest.raises(ValidationError):
        Settings(database_url="sqlite://")
    with pytest.raises(ValidationError):
        Settings(database_url="postgresql+psycopg://localhost/test", cors_origins=["*"])


def test_validation_does_not_echo_password(client):
    secret = "private-value" * 20
    response = client.post("/api/v1/auth/login", json={"email": "invalid", "password": secret})
    assert response.status_code == 422
    assert secret not in response.text
    assert "input" not in response.text


def test_cors_and_openapi(client):
    for origin, code in [("http://localhost:4200", 200), ("https://unknown.example", 400)]:
        response = client.options(
            "/api/v1/admin/projects",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization",
            },
        )
        assert response.status_code == code
    paths = client.get("/openapi.json").json()["paths"]
    for path, methods in paths.items():
        if path.startswith("/api/v1/admin/") or path in {"/api/v1/auth/me", "/api/v1/auth/logout"}:
            for operation in methods.values():
                assert {"HTTPBearer": []} in operation["security"]
