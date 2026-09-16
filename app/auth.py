from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from urllib.parse import quote

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint


PBKDF2_ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 310_000
MAX_LOGIN_ATTEMPTS = 5
LOGIN_WINDOW_SECONDS = 300
PUBLIC_PATHS = {"/health", "/login"}
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


@dataclass(frozen=True)
class AuthConfig:
    username: str
    password_hash: str

    @property
    def configured(self) -> bool:
        return bool(self.username and self.password_hash)


_attempts: dict[str, deque[float]] = defaultdict(deque)
_attempt_lock = threading.Lock()


def auth_config() -> AuthConfig:
    return AuthConfig(
        username=os.getenv("APP_USERNAME", ""),
        password_hash=os.getenv("APP_PASSWORD_HASH", ""),
    )


def hash_password(password: str, *, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
    salt_value = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt_value.encode(), iterations).hex()
    return f"{PBKDF2_ALGORITHM}${iterations}${salt_value}${digest}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        algorithm, raw_iterations, salt, expected = encoded.split("$", 3)
        iterations = int(raw_iterations)
    except (TypeError, ValueError):
        return False
    if algorithm != PBKDF2_ALGORITHM or iterations < 1:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), iterations).hex()
    return hmac.compare_digest(actual, expected)


def csrf_token(request: Request) -> str:
    token = request.session.get("csrf_token")
    if not token:
        token = secrets.token_urlsafe(32)
        request.session["csrf_token"] = token
    return token


def login_is_throttled(key: str, *, now: float | None = None) -> bool:
    current = time.monotonic() if now is None else now
    with _attempt_lock:
        attempts = _attempts[key]
        while attempts and attempts[0] <= current - LOGIN_WINDOW_SECONDS:
            attempts.popleft()
        return len(attempts) >= MAX_LOGIN_ATTEMPTS


def record_login_failure(key: str, *, now: float | None = None) -> None:
    current = time.monotonic() if now is None else now
    with _attempt_lock:
        _attempts[key].append(current)


def clear_login_failures(key: str) -> None:
    with _attempt_lock:
        _attempts.pop(key, None)


def reset_login_attempts() -> None:
    with _attempt_lock:
        _attempts.clear()


def client_key(request: Request) -> str:
    return request.client.host if request.client else "unknown"


class AuthenticationMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        path = request.url.path
        if path.startswith("/static/") or path in PUBLIC_PATHS:
            return await call_next(request)

        if not request.session.get("authenticated"):
            if path.startswith("/api/"):
                return JSONResponse({"detail": "로그인이 필요합니다."}, status_code=401)
            destination = quote(path + (f"?{request.url.query}" if request.url.query else ""), safe="")
            return RedirectResponse(f"/login?next={destination}", status_code=303)

        expected = csrf_token(request)
        if request.method in UNSAFE_METHODS:
            supplied = request.headers.get("X-CSRF-Token", "")
            content_type = request.headers.get("content-type", "")
            if not supplied and content_type.startswith("application/x-www-form-urlencoded"):
                form = await request.form()
                supplied = str(form.get("csrf_token", ""))
            if not supplied or not hmac.compare_digest(supplied, expected):
                return JSONResponse({"detail": "CSRF token validation failed."}, status_code=403)

        request.state.csrf_token = expected
        return await call_next(request)
