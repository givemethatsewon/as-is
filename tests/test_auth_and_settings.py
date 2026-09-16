from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.auth import hash_password, reset_login_attempts, verify_password
from app.db import get_db
from app.main import app


def test_pbkdf2_password_hash_verification() -> None:
    encoded = hash_password("correct horse", salt="fixed-salt", iterations=1000)

    assert verify_password("correct horse", encoded)
    assert not verify_password("wrong", encoded)


def test_non_health_routes_require_login_and_api_returns_401(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: iter([db_session])
    with TestClient(app, base_url="https://testserver") as raw:
        page = raw.get("/inventory", follow_redirects=False)
        api = raw.get("/api/inventory")
        health = raw.get("/health")
    app.dependency_overrides.clear()

    assert page.status_code == 303
    assert page.headers["location"].startswith("/login")
    assert api.status_code == 401
    assert health.status_code == 200


def test_login_sets_secure_session_and_csrf_blocks_missing_token(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: iter([db_session])
    reset_login_attempts()
    with TestClient(app, base_url="https://testserver") as raw:
        login_page = raw.get("/login")
        token = re.search(r'name="csrf_token" value="([^"]+)"', login_page.text).group(1)
        login = raw.post(
            "/login",
            data={"username": "demo", "password": "demo-pass", "csrf_token": token},
            follow_redirects=False,
        )
        blocked = raw.post("/api/imports/confirm", data={"batch_id": "missing"})
    app.dependency_overrides.clear()

    cookie = login.headers["set-cookie"].lower()
    assert login.status_code == 303
    assert "httponly" in cookie
    assert "secure" in cookie
    assert "samesite=lax" in cookie
    assert blocked.status_code == 403


def test_login_is_throttled_after_repeated_failures(db_session) -> None:
    app.dependency_overrides[get_db] = lambda: iter([db_session])
    reset_login_attempts()
    with TestClient(app, base_url="https://testserver", client=("198.51.100.8", 50000)) as raw:
        token = re.search(r'name="csrf_token" value="([^"]+)"', raw.get("/login").text).group(1)
        responses = [
            raw.post(
                "/login",
                data={"username": "demo", "password": "wrong", "csrf_token": token},
                follow_redirects=False,
            )
            for _ in range(6)
        ]
    app.dependency_overrides.clear()

    assert responses[-1].status_code == 429
