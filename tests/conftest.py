from __future__ import annotations

from collections.abc import Generator
import hashlib
import os
import re
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

_TEST_SALT = "test-salt"
_TEST_DIGEST = hashlib.pbkdf2_hmac("sha256", b"demo-pass", _TEST_SALT.encode(), 310_000).hex()
os.environ.setdefault("APP_USERNAME", "demo")
os.environ.setdefault("APP_PASSWORD_HASH", f"pbkdf2_sha256$310000${_TEST_SALT}${_TEST_DIGEST}")
os.environ.setdefault("SESSION_SECRET", "test-session-secret-at-least-32-characters")
os.environ.setdefault("COOKIE_SECURE", "true")

from app.db import Base, get_db
from app.main import app


@pytest.fixture()
def db_session() -> Generator[Session, None, None]:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(engine)


@pytest.fixture()
def client(db_session: Session):
    def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db
    from fastapi.testclient import TestClient

    with TestClient(app, base_url="https://testserver") as test_client:
        login_page = test_client.get("/login")
        csrf_token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
        response = test_client.post(
            "/login",
            data={"username": "demo", "password": "demo-pass", "csrf_token": csrf_token},
        )
        assert response.status_code == 200
        test_client.headers["X-CSRF-Token"] = csrf_token
        yield test_client
    app.dependency_overrides.clear()
