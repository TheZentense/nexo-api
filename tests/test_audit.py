import os
import secrets
from uuid import uuid4

import pytest
from sqlalchemy import text, update
from sqlalchemy.orm import Session

from app.modules.auth.models import AdminUser
from app.modules.auth.security import password_hasher
from tests.helpers import login, new_project

pytestmark = pytest.mark.skipif(
    not os.getenv("TEST_DATABASE_URL"),
    reason="Set TEST_DATABASE_URL for PostgreSQL integration tests",
)


def audit_events(engine, record_id):
    with engine.connect() as conn:
        return (
            conn.execute(
                text("SELECT * FROM audit.events WHERE record_id=:id ORDER BY id"),
                {"id": record_id},
            )
            .mappings()
            .all()
        )


def test_audit_records_actor_values_and_state(account):
    client, engine, user_id, _, _ = account
    login(account)
    project, data = new_project(client)
    route = "/api/v1/admin/projects/" + project["id"]
    client.patch(route, json={"version": 1, "progress_percent": 40})
    client.post(route + "/publish", json={"version": 2})
    client.post(route + "/archive", json={"version": 3})
    events = audit_events(engine, project["id"])
    assert [e["action"] for e in events] == ["insert", "update", "published", "archived"]
    assert all(
        e["actor_id"] == user_id and e["request_id"] and e["occurred_at"] and e["database_user"]
        for e in events
    )
    assert len({e["request_id"] for e in events}) == 4
    assert events[0]["before_data"] is None
    assert events[1]["before_data"]["progress_percent"] == 0
    assert events[1]["after_data"]["progress_percent"] == 40
    category_events = audit_events(engine, data["category_id"])
    assert category_events[0]["actor_id"] == user_id
    assert category_events[0]["table_name"] == "categories"
    client.patch(
        "/api/v1/admin/categories/" + data["category_id"],
        json={"name": "Changed " + uuid4().hex, "slug": "changed-" + uuid4().hex},
    )
    assert len(audit_events(engine, data["category_id"])) == 2


def test_rejected_edits_and_reads_do_not_add_audit_events(account):
    client, engine, _, _, _ = account
    login(account)
    project, _ = new_project(client)
    route = "/api/v1/admin/projects/" + project["id"]
    assert client.patch(route, json={"version": 999, "title": "Rejected"}).status_code == 409
    assert (
        client.post(
            route + "/archive", json={"version": 1}, headers={"Authorization": ""}
        ).status_code
        == 401
    )
    assert client.get(route).status_code == 200
    assert len(audit_events(engine, project["id"])) == 1


def test_audit_rollback_and_context_cleanup(migrated_database):
    from app.core.audit import set_audit_context

    engine, _, _, _ = migrated_database
    actor, record = uuid4(), uuid4()
    with engine.connect() as conn:
        with Session(bind=conn) as db:
            set_audit_context(db, actor)
            db.execute(
                text("INSERT INTO categories(id,name,slug) VALUES (:id,:name,:slug)"),
                {"id": record, "name": str(record), "slug": str(record)},
            )
            db.rollback()
        assert (
            conn.execute(text("SELECT nullif(current_setting('app.actor_id',true),'')")).scalar()
            is None
        )
        assert (
            conn.execute(text("SELECT nullif(current_setting('app.request_id',true),'')")).scalar()
            is None
        )
    assert audit_events(engine, record) == []


def test_audit_credentials_are_filtered(account):
    _, engine, user_id, email, password = account
    with Session(engine) as db, db.begin():
        db.execute(
            update(AdminUser)
            .where(AdminUser.id == user_id)
            .values(password_hash=password_hasher.hash(secrets.token_urlsafe(32)))
        )
    events = audit_events(engine, user_id)
    assert events[-1]["action"] == "credentials_changed"
    for event in events:
        for data in [event["before_data"], event["after_data"]]:
            if data is not None:
                assert set(data) == {"id", "is_active"}
                assert email not in str(data) and password not in str(data)
    with engine.connect() as conn:
        assert (
            conn.execute(
                text(
                    "SELECT count(*) FROM audit.events WHERE table_name IN ('admin_sessions','auth_rate_limits')"
                )
            ).scalar()
            == 0
        )


def test_database_role_cannot_modify_history(migrated_database):
    from sqlalchemy.exc import DBAPIError

    engine, _, _, _ = migrated_database
    role = "nexo_audit_test_" + uuid4().hex
    record = uuid4()
    with engine.connect() as conn:
        transaction = conn.begin()
        try:
            # El rol y sus permisos desaparecen al revertir esta transacción.
            conn.execute(text(f'CREATE ROLE "{role}" NOLOGIN'))
            conn.execute(text(f'GRANT USAGE ON SCHEMA public TO "{role}"'))
            conn.execute(text(f'GRANT INSERT ON public.categories TO "{role}"'))
            conn.execute(text(f'SET LOCAL ROLE "{role}"'))
            conn.execute(
                text("INSERT INTO public.categories(id,name,slug) VALUES (:id,:name,:slug)"),
                {"id": record, "name": str(record), "slug": str(record)},
            )
            for sql in [
                "SELECT * FROM audit.events",
                "DELETE FROM audit.events",
                "UPDATE audit.events SET action='changed'",
                "TRUNCATE audit.events",
                "INSERT INTO audit.events(table_name) VALUES ('fake')",
                "ALTER TABLE public.categories DISABLE TRIGGER categories_audit",
            ]:
                with pytest.raises(DBAPIError), conn.begin_nested():
                    conn.execute(text(sql))
            conn.execute(text("RESET ROLE"))
            assert (
                conn.execute(
                    text("SELECT count(*) FROM audit.events WHERE record_id=:id"), {"id": record}
                ).scalar()
                == 1
            )
        finally:
            transaction.rollback()


def test_direct_sql_delete_is_audited(migrated_database):
    engine, _, _, _ = migrated_database
    record = uuid4()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO categories(id,name,slug) VALUES (:id,:name,:slug)"),
            {"id": record, "name": str(record), "slug": str(record)},
        )
        conn.execute(text("DELETE FROM categories WHERE id=:id"), {"id": record})
    events = audit_events(engine, record)
    assert [e["operation"] for e in events] == ["INSERT", "DELETE"]
    assert events[-1]["before_data"]["id"] == str(record)
    assert events[-1]["after_data"] is None
    assert events[-1]["actor_id"] is None


def test_audit_is_not_exposed_in_http(account):
    client, _, _, _, _ = account
    login(account)
    paths = client.get("/openapi.json").json()["paths"]
    assert not any("audit" in path for path in paths)
