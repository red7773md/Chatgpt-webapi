"""Builds the app for Vercel and local runs. A missing setting becomes a readable 503."""

from __future__ import annotations

from collections.abc import Mapping

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from .config import ConfigError, load_settings
from .main import create_app


def build_entrypoint(env: Mapping[str, str] | None = None) -> FastAPI:
    try:
        settings = load_settings(env)
    except ConfigError as exc:
        app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

        @app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
        async def setup_needed(path: str) -> JSONResponse:
            return JSONResponse(status_code=503, content={"detail": str(exc)})

        return app
    return create_app(settings)


app = build_entrypoint()
