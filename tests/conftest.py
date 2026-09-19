import os
import secrets
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.main import create_app
from app.modules.auth.models import AdminUser
from app.modules.auth.security import password_hasher


@pytest.fixture(autouse=True)
def test_signing_key(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))


@pytest.fixture(scope="module")
def migrated_database():
    source = make_url(os.environ["TEST_DATABASE_URL"])
    name = "nexo_test_" + uuid4().hex
    control = create_engine(
        source.set(database="postgres"),
        isolation_level="AUTOCOMMIT",
        hide_parameters=True,
        connect_args={"connect_timeout": 5},
    )
    target_url = source.set(database=name)
    engine = create_engine(target_url, hide_parameters=True)
    config = Config("alembic.ini")
    changes = pytest.MonkeyPatch()
    with control.connect() as conn:
        conn.execute(text(f'CREATE DATABASE "{name}"'))
    try:
        changes.setenv("DATABASE_URL", target_url.render_as_string(hide_password=False))
        changes.setenv("MIGRATION_DATABASE_URL", target_url.render_as_string(hide_password=False))
        command.upgrade(config, "0001_projects")
        retained_id = uuid4()
        with engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO projects(id,title,slug,status) VALUES (:id,'Existing project','existing-project','draft')"
                ),
                {"id": retained_id},
            )
            before = dict(
                conn.execute(text("SELECT * FROM projects WHERE id=:id"), {"id": retained_id})
                .mappings()
                .one()
            )
        command.upgrade(config, "head")
        command.check(config)
        with engine.connect() as conn:
            after = dict(
                conn.execute(text("SELECT * FROM projects WHERE id=:id"), {"id": retained_id})
                .mappings()
                .one()
            )
        yield engine, target_url, before, after
    finally:
        changes.undo()
        engine.dispose()
        # Solo se elimina la base temporal creada por esta prueba.
        assert name.startswith("nexo_test_") and len(name) == 42
        with control.connect() as conn:
            conn.execute(text(f'DROP DATABASE "{name}" WITH (FORCE)'))
        control.dispose()


@pytest.fixture
def account(migrated_database):
    engine, url, _, _ = migrated_database
    identifier = uuid4().hex
    email = f"test-{identifier}@example.com"
    password = secrets.token_urlsafe(32)
    with Session(engine) as db, db.begin():
        user = AdminUser(email=email, password_hash=password_hasher.hash(password))
        db.add(user)
        db.flush()
        user_id = user.id
    app = create_app(Settings(database_url=url.render_as_string(hide_password=False)))
    with TestClient(app, client=(identifier, 50000)) as client:
        yield client, engine, user_id, email, password
