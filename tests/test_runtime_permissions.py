import io
import os
from uuid import uuid4

import pytest
from PIL import Image
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.modules.auth.router import database
from app.modules.media.storage import LocalStorage
from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(not os.getenv("TEST_DATABASE_URL"), reason="PostgreSQL required")


def test_api_flows_with_restricted_database_role(account, tmp_path):
    client, engine, user_id, *_ = account
    client.app.state.storage = LocalStorage(tmp_path / "storage")
    role = "nexo_runtime_test_" + uuid4().hex
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            grants = [
                "GRANT USAGE ON SCHEMA public",
                "GRANT SELECT ON admin_users",
                "GRANT UPDATE(password_hash) ON admin_users",
                "GRANT SELECT,INSERT,DELETE ON admin_sessions",
                "GRANT SELECT,INSERT,UPDATE ON auth_rate_limits,categories,projects,project_videos,project_images",
                "GRANT SELECT,INSERT ON contact_messages,volunteer_applications",
                "GRANT UPDATE(handled_at) ON contact_messages",
                "GRANT UPDATE(status,version,updated_at) ON volunteer_applications",
            ]
            for grant in grants:
                connection.execute(text(f'{grant} TO "{role}"'))
            connection.execute(text(f'SET LOCAL ROLE "{role}"'))

            def runtime_database():
                # Las peticiones comparten la conexión para revertir también el rol al terminar.
                with Session(bind=connection, join_transaction_mode="create_savepoint") as db:
                    yield db

            client.app.dependency_overrides[database] = runtime_database
            login(account)
            project, _ = new_project(client)
            published = client.post(
                f"/api/v1/admin/projects/{project['id']}/publish", json={"version": 1}
            )
            assert published.status_code == 200
            assert client.get(f"/api/v1/projects/{project['slug']}").status_code == 200
            assert client.get("/api/v1/admin/dashboard").status_code == 200

            email = f"{uuid4().hex}@example.com"
            assert (
                client.post(
                    "/api/v1/contact-messages",
                    json={"name": "Example", "email": email, "message": "Example message"},
                ).status_code
                == 201
            )
            contacts = client.get("/api/v1/admin/contact-messages").json()["items"]
            contact = next(item for item in contacts if item["email"] == email)
            assert (
                client.post(f"/api/v1/admin/contact-messages/{contact['id']}/handle").status_code
                == 200
            )

            assert (
                client.post(
                    "/api/v1/volunteer-applications",
                    json={"name": "Example", "email": email, "area": "education"},
                ).status_code
                == 201
            )
            applications = client.get("/api/v1/admin/volunteer-applications").json()["items"]
            application = next(item for item in applications if item["email"] == email)
            accepted = client.patch(
                f"/api/v1/admin/volunteer-applications/{application['id']}/status",
                json={"status": "accepted", "version": 1},
            )
            assert accepted.status_code == 200

            source = io.BytesIO()
            Image.new("RGB", (16, 16), "green").save(source, format="PNG")
            uploaded = client.post(
                f"/api/v1/admin/projects/{project['id']}/images",
                content=source.getvalue(),
                headers={"Content-Type": "image/png"},
            )
            assert uploaded.status_code == 202
            original = client.get(f"/api/v1/admin/images/{uploaded.json()['id']}/original")
            assert original.status_code == 200 and original.content == source.getvalue()
            gallery = client.get(f"/api/v1/admin/projects/{project['id']}/images").json()
            assert (
                client.post(
                    f"/api/v1/admin/images/{uploaded.json()['id']}/archive",
                    json={"version": gallery["project_version"]},
                ).status_code
                == 200
            )
            assert client.post("/api/v1/auth/logout").status_code == 204
            assert client.get("/api/v1/admin/contact-messages").status_code == 401

            for statement in (
                "DELETE FROM audit.events",
                "DELETE FROM contact_messages",
                "UPDATE volunteer_applications SET email='changed@example.com'",
            ):
                with pytest.raises(DBAPIError), connection.begin_nested():
                    connection.execute(text(statement))
            connection.execute(text("RESET ROLE"))
            for identifier in (contact["id"], application["id"]):
                event = connection.execute(
                    text("SELECT actor_id FROM audit.events WHERE record_id=:id"),
                    {"id": identifier},
                ).scalar_one()
                assert event == user_id
        finally:
            client.app.dependency_overrides.pop(database, None)
            transaction.rollback()
