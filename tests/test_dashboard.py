import os
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from app.core.database import Base
from app.modules.projects.models import Project
from app.modules.projects.service import dashboard
from tests.helpers import login, new_project


@pytest.fixture
def dashboard_db():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        yield db
    engine.dispose()


def test_empty_dashboard(dashboard_db):
    assert dashboard(dashboard_db) == {
        "total": 0,
        "draft": 0,
        "published": 0,
        "archived": 0,
        "recent": [],
    }


def test_counts_include_all_projects_and_recent_is_limited(dashboard_db):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    states = ["draft", "published", "archived", "draft", "published", "draft", "draft"]
    for number, status in enumerate(states, 1):
        dashboard_db.add(
            Project(
                id=UUID(int=number),
                title=f"Project {number}",
                slug=f"project-{number}",
                status=status,
                updated_at=start + timedelta(days=number),
            )
        )
    dashboard_db.commit()
    result = dashboard(dashboard_db)
    assert {key: result[key] for key in ["total", "draft", "published", "archived"]} == {
        "total": 7,
        "draft": 4,
        "published": 2,
        "archived": 1,
    }
    assert [p.id.int for p in result["recent"]] == [7, 6, 5, 4, 3]


def test_missing_statuses_and_equal_dates(dashboard_db):
    timestamp = datetime(2026, 1, 1, tzinfo=UTC)
    for number in [2, 1, 3]:
        dashboard_db.add(
            Project(
                id=UUID(int=number),
                title="Example",
                slug=f"example-{number}",
                status="draft",
                updated_at=timestamp,
            )
        )
    dashboard_db.commit()
    result = dashboard(dashboard_db)
    assert result["published"] == result["archived"] == 0
    assert result["draft"] == result["total"] == 3
    assert [p.id.int for p in result["recent"]] == [3, 2, 1]


requires_postgres = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


@requires_postgres
def test_dashboard_requires_active_session(account):
    client, _, _, _, _ = account
    route = "/api/v1/admin/dashboard"
    assert client.get(route).status_code == 401
    login(account)
    assert client.get(route).status_code == 200
    assert client.post("/api/v1/auth/logout").status_code == 204
    assert client.get(route).status_code == 401


@requires_postgres
def test_dashboard_reflects_edits_and_does_not_write_audit(account):
    client, engine, _, _, _ = account
    login(account)
    route = "/api/v1/admin/dashboard"
    baseline = client.get(route).json()
    first, _ = new_project(client)
    second, _ = new_project(client)
    changed = client.patch(
        "/api/v1/admin/projects/" + first["id"], json={"version": 1, "title": "Updated title"}
    )
    assert changed.status_code == 200
    result = client.get(route)
    assert result.status_code == 200
    assert result.headers["cache-control"] == "no-store"
    data = result.json()
    assert data["total"] == baseline["total"] + 2
    assert data["draft"] == baseline["draft"] + 2
    assert data["recent"][0]["id"] == first["id"]
    assert data["recent"][0]["title"] == "Updated title"
    assert (
        client.post(
            "/api/v1/admin/projects/" + second["id"] + "/publish", json={"version": 1}
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/v1/admin/projects/" + first["id"] + "/archive", json={"version": 2}
        ).status_code
        == 200
    )
    data = client.get(route).json()
    assert data["draft"] == baseline["draft"]
    assert data["published"] == baseline["published"] + 1
    assert data["archived"] == baseline["archived"] + 1
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM audit.events")).scalar()
    client.get(route)
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit.events")).scalar() == before
    paths = client.get("/openapi.json").json()["paths"]
    assert {"HTTPBearer": []} in paths[route]["get"]["security"]
    assert "/api/v1/dashboard" not in paths
