import secrets

import pytest


@pytest.fixture(autouse=True)
def test_signing_key(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", secrets.token_urlsafe(48))
