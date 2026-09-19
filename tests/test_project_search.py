import os
from uuid import uuid4

import pytest
from sqlalchemy import text

from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


@pytest.fixture
def search_catalog(account):
    client, engine, _, _, _ = account
    login(account)
    _, data = new_project(client)
    category = data["category_id"]
    records = []
    for title, year, status in [
        ("Community Classes", 2026, "draft"),
        ("COMMUNITY health", 2025, "published"),
        ("Community garden", 2026, "archived"),
        ("Other activity", 2026, "draft"),
        ("Progress 50%_done / test", 2026, "draft"),
    ]:
        response = client.post(
            "/api/v1/admin/projects",
            json={
                **data,
                "slug": "search-" + uuid4().hex,
                "title": title,
                "project_date": f"{year}-01-01",
                "description": "Community appears only in the description here.",
            },
        )
        assert response.status_code == 201
        record = response.json()
        if status != "draft":
            action = "publish" if status == "published" else "archive"
            assert (
                client.post(
                    f"/api/v1/admin/projects/{record['id']}/{action}", json={"version": 1}
                ).status_code
                == 200
            )
        records.append(record)
    return client, engine, category, records


def test_title_search_trims_spaces_and_ignores_case(search_catalog):
    client, _, category, _ = search_catalog
    response = client.get(
        "/api/v1/admin/projects", params={"q": "  cOmMuNiTy  ", "category_id": category}
    )
    assert response.status_code == 200
    result = response.json()
    assert result["total"] == 3
    assert {p["status"] for p in result["items"]} == {"draft", "published", "archived"}
    assert response.headers["cache-control"] == "no-store"


def test_search_combines_filters_and_pagination(search_catalog):
    client, _, category, _ = search_catalog
    params = {"q": "community", "category_id": category, "year": 2026, "status": "draft"}
    result = client.get("/api/v1/admin/projects", params=params).json()
    assert result["total"] == 1 and result["items"][0]["title"] == "Community Classes"
    params = {"q": "community", "category_id": category, "page_size": 1}
    pages = [
        client.get("/api/v1/admin/projects", params={**params, "page": page}).json()
        for page in [1, 2, 3, 4]
    ]
    assert all(p["total"] == 3 for p in pages)
    assert len({p["items"][0]["id"] for p in pages[:3]}) == 3
    assert pages[3]["items"] == []
    assert (
        client.get("/api/v1/admin/projects", params={**params, "category_id": str(uuid4())}).json()[
            "total"
        ]
        == 0
    )


@pytest.mark.parametrize("query", ["%", "_", "/", "50%_done"])
def test_wildcards_are_literal_text(search_catalog, query):
    client, _, category, _ = search_catalog
    result = client.get(
        "/api/v1/admin/projects", params={"q": query, "category_id": category}
    ).json()
    assert result["total"] == 1
    assert result["items"][0]["title"] == "Progress 50%_done / test"


def test_empty_search_and_missing_results(search_catalog):
    client, _, category, _ = search_catalog
    expected = client.get("/api/v1/admin/projects", params={"category_id": category}).json()
    for query in ["", "   "]:
        assert (
            client.get(
                "/api/v1/admin/projects", params={"q": query, "category_id": category}
            ).json()
            == expected
        )
    for query in ["missing-title", "' OR 1=1 --"]:
        result = client.get(
            "/api/v1/admin/projects", params={"q": query, "category_id": category}
        ).json()
        assert result["total"] == 0 and result["items"] == []


def test_search_requires_auth_and_limits_input(search_catalog):
    client, _, _, _ = search_catalog
    assert (
        client.get(
            "/api/v1/admin/projects", params={"q": "community"}, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert client.get("/api/v1/admin/projects", params={"q": "x" * 201}).status_code == 422
    assert client.get("/api/v1/admin/projects", params={"q": "x" * 200}).status_code == 200


def test_search_does_not_write_audit_or_expose_drafts(search_catalog):
    client, engine, category, _ = search_catalog
    with engine.connect() as conn:
        before = conn.execute(text("SELECT count(*) FROM audit.events")).scalar()
    client.get("/api/v1/admin/projects", params={"q": "community", "category_id": category})
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM audit.events")).scalar() == before
    result = client.get(
        "/api/v1/projects", params={"category_id": category, "q": "community"}
    ).json()
    assert result["total"] == 1 and result["items"][0]["title"] == "COMMUNITY health"
    paths = client.get("/openapi.json").json()["paths"]
    assert "q" not in {p["name"] for p in paths["/api/v1/projects"]["get"]["parameters"]}

