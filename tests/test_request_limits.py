import asyncio

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.request_limits import PUBLIC_FORM_MAX_BYTES, PublicFormLimit
from app.main import create_app


@pytest.mark.parametrize(
    "path",
    ["/api/v1/contact-messages", "/api/v1/volunteer-applications", "/api/v1/contact-messages/"],
)
def test_oversized_forms_rejected_before_database_access(path):
    app = create_app(Settings(database_url="postgresql+psycopg://localhost/unused"))
    with TestClient(app) as client:
        response = client.post(
            path,
            content=b"x" * (PUBLIC_FORM_MAX_BYTES + 1),
            headers={"Content-Type": "application/json", "Origin": "http://localhost:4200"},
        )
    assert response.status_code == 413
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["access-control-allow-origin"] == "http://localhost:4200"


def run_request(chunks, headers=(), path="/api/v1/contact-messages"):
    result = {"body": None, "messages": []}

    async def app(scope, receive, send):
        message = await receive()
        result["body"] = message.get("body")

    async def receive():
        return chunks.pop(0)

    async def send(message):
        result["messages"].append(message)

    scope = {"type": "http", "method": "POST", "path": path, "headers": list(headers)}
    asyncio.run(PublicFormLimit(app)(scope, receive, send))
    return result


@pytest.mark.parametrize("headers", [(), ((b"content-length", b"1"),)])
def test_chunked_body_limit_without_trusting_length(headers):
    result = run_request(
        [
            {"type": "http.request", "body": b"a" * PUBLIC_FORM_MAX_BYTES, "more_body": True},
            {"type": "http.request", "body": b"b", "more_body": False},
        ],
        headers,
    )
    assert result["body"] is None
    assert result["messages"][0]["status"] == 413


def test_body_at_limit_preserves_all_chunks():
    chunks = [
        {"type": "http.request", "body": b"a" * 100, "more_body": True},
        {"type": "http.request", "body": b"b" * (PUBLIC_FORM_MAX_BYTES - 100), "more_body": False},
    ]
    result = run_request(chunks)
    assert result["body"] == b"a" * 100 + b"b" * (PUBLIC_FORM_MAX_BYTES - 100)


@pytest.mark.parametrize("length", [b"bad", b"-1"])
def test_invalid_length_is_rejected(length):
    result = run_request([], ((b"content-length", length),))
    assert result["messages"][0]["status"] == 400
    assert result["body"] is None


def test_disconnected_request_does_not_reach_handler():
    result = run_request([{"type": "http.disconnect"}])
    assert result["body"] is None and result["messages"] == []


def test_media_upload_keeps_its_own_limit():
    content = b"x" * (PUBLIC_FORM_MAX_BYTES + 1)
    result = run_request(
        [{"type": "http.request", "body": content}], path="/api/v1/admin/projects/example/videos"
    )
    assert result["body"] == content
