from uuid import uuid4


def login(account):
    client, _, _, email, password = account
    response = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert response.status_code == 200
    client.headers["Authorization"] = "Bearer " + response.json()["access_token"]
    return response


def new_project(client):
    slug = "example-" + uuid4().hex
    category = client.post("/api/v1/admin/categories", json={"name": slug, "slug": slug})
    assert category.status_code == 201
    data = {
        "title": "Example project",
        "slug": slug,
        "category_id": category.json()["id"],
        "project_date": "2026-01-01",
        "short_description": "Example summary",
        "description": "Example description",
        "location": "Example location",
    }
    response = client.post("/api/v1/admin/projects", json=data)
    assert response.status_code == 201
    return response.json(), data
