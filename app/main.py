"""FastAPI application: admin login, the ChatGPT session token, chats, and the MCP endpoint at /mcp."""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.requests import Request as StarletteRequest
from starlette.middleware.sessions import SessionMiddleware

from .chat_service import ChatService
from .chatgpt_backend import ChatBackend, NotConnectedBackend
from .config import BASE_DIR, Settings, load_settings
from .feature_routes import chat_router
from .mcp_tools import build_mcp
from .records import JsonStore, register_error_handlers
from .security import LoginThrottle, credentials_match
from .storage import BlobStore, KeyValueStore, LocalFileStore
from .token_store import TokenStore

SESSION_COOKIE = "chatgpt_archive_session"
SESSION_MAX_AGE = 8 * 60 * 60
STATIC_DIR = BASE_DIR / "static"
# Scripts and styles come only from this app. Fonts come from Google Fonts, as in the Gemini app.
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' https://fonts.googleapis.com; "
    "font-src https://fonts.gstatic.com; img-src 'self' data:; connect-src 'self'; "
    "base-uri 'none'; form-action 'self'; frame-ancestors 'none'"
)


class LoginIn(BaseModel):
    username: str = Field(max_length=200)
    password: str = Field(max_length=500)


class TokenIn(BaseModel):
    token: str = Field(min_length=1, max_length=8200)


def _client_key(request: Request, behind_proxy: bool) -> str:
    if behind_proxy:
        first = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if first:
            return first
    return request.client.host if request.client else "unknown"


def create_app(
    settings: Settings | None = None,
    backend: ChatBackend | None = None,
    store: KeyValueStore | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    if store is None:
        store = BlobStore(settings.blob_token) if settings.blob_token else LocalFileStore(settings.data_dir)
    records = JsonStore(store)
    tokens = TokenStore(records)
    chats = ChatService(backend or NotConnectedBackend(), records, tokens)
    throttle = LoginThrottle()
    mcp = build_mcp(chats)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(title="ChatGPT Archive", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=SESSION_COOKIE,
        max_age=SESSION_MAX_AGE,
        same_site="strict",
        https_only=settings.cookie_secure,
    )
    register_error_handlers(app)

    @app.middleware("http")
    async def security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CSP
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store"
        return response

    def require_admin(request: Request) -> str:
        if not request.session.get("admin"):
            raise HTTPException(status_code=401, detail="Login required.")
        return str(request.session.get("user", ""))

    def presented_key(request: Request) -> str:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            return auth[7:].strip()
        return request.headers.get("x-api-key", "").strip() or request.query_params.get("key", "").strip()

    def key_is_valid(request: Request) -> bool:
        """Checks the app's API key. Wrong keys are throttled per client, apart from failed logins."""
        if not settings.api_key:
            return False
        provided = presented_key(request)
        throttle_key = "key:" + _client_key(request, settings.on_vercel)
        wait = throttle.retry_after(throttle_key)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {int(wait) + 1}s.",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        if not provided:
            return False
        if secrets.compare_digest(provided.encode(), settings.api_key.encode()):
            throttle.record_success(throttle_key)
            return True
        throttle.record_failure(throttle_key)
        return False

    def require_user(request: Request) -> str:
        """Chat routes accept a browser login or the API key."""
        if request.session.get("admin"):
            return str(request.session.get("user", ""))
        if key_is_valid(request):
            return "api"
        raise HTTPException(status_code=401, detail="Login or an API key is required.")

    admin = Depends(require_admin)

    # ----- public ------------------------------------------------------------

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/healthz")
    async def healthz() -> dict[str, bool]:
        return {"ok": True}

    # ----- auth --------------------------------------------------------------

    @app.post("/api/auth/login")
    async def login(body: LoginIn, request: Request) -> dict[str, Any]:
        key = _client_key(request, settings.on_vercel)
        wait = throttle.retry_after(key)
        if wait > 0:
            raise HTTPException(
                status_code=429,
                detail=f"Too many failed attempts. Try again in {int(wait) + 1}s.",
                headers={"Retry-After": str(int(wait) + 1)},
            )
        if not credentials_match(body.username, body.password, settings.admin_username, settings.admin_password):
            throttle.record_failure(key)
            raise HTTPException(status_code=401, detail="Invalid username or password.")
        throttle.record_success(key)
        request.session.clear()
        request.session["admin"] = True
        request.session["user"] = settings.admin_username
        return {"ok": True, "username": settings.admin_username}

    @app.post("/api/auth/logout")
    async def logout(request: Request) -> dict[str, bool]:
        request.session.clear()
        return {"ok": True}

    @app.get("/api/auth/me")
    async def me(request: Request) -> dict[str, Any]:
        if request.session.get("admin"):
            return {"logged_in": True, "username": str(request.session.get("user", ""))}
        return {"logged_in": False}

    # ----- ChatGPT session token (admin only) --------------------------------

    @app.get("/api/session", dependencies=[admin])
    async def session_status() -> dict[str, Any]:
        return {"token": await tokens.status(), "storage": settings.storage_label}

    @app.post("/api/session/token", dependencies=[admin])
    async def save_token(body: TokenIn) -> dict[str, Any]:
        return {"token": await tokens.save(body.token)}

    @app.delete("/api/session/token", dependencies=[admin])
    async def clear_token() -> dict[str, bool]:
        await tokens.clear()
        return {"ok": True}

    # ----- feature routes ----------------------------------------------------

    app.include_router(chat_router(chats, require_user))

    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    # ----- MCP endpoint ------------------------------------------------------
    # Mounted last so it only answers paths nothing else claimed. Only /mcp is served.

    mcp_app = mcp.streamable_http_app()

    async def mcp_guard(scope, receive, send):
        if scope["type"] != "http":
            return
        if scope["path"] != "/mcp":
            response = JSONResponse({"detail": "Not found."}, status_code=404)
        else:
            request = StarletteRequest(scope, receive)
            if key_is_valid(request):
                await mcp_app(scope, receive, send)
                return
            response = JSONResponse({"detail": "An API key is required for MCP."}, status_code=401)
        await response(scope, receive, send)

    app.mount("/", mcp_guard)
    return app
