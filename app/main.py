from contextlib import asynccontextmanager
from os import getenv
import secrets

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from app.auth import AuthenticationMiddleware
from app.db import init_db
from app.routers import api, pages


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="처음처럼 - 원상태수출관리", version="0.1.0", lifespan=lifespan)
app.add_middleware(AuthenticationMiddleware)
app.add_middleware(
    SessionMiddleware,
    secret_key=getenv("SESSION_SECRET") or secrets.token_urlsafe(48),
    session_cookie="as_is_session",
    same_site="lax",
    https_only=getenv("COOKIE_SECURE", "true").lower() not in {"0", "false", "no"},
    max_age=8 * 60 * 60,
)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
app.include_router(api.router)
app.include_router(pages.router)


@app.get("/health")
def health():
    return {"status": "ok"}
