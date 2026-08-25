"""Modeem AI Platform — API entrypoint."""

from app.core.paths import ensure_shared_packages_importable

ensure_shared_packages_importable()

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.connections import router as connections_router
from app.api.content_manager import router as content_manager_router
from app.api.v1 import router as v1_router
from app.core.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version=settings.app_version)

    # Allow all origins so the proxied Next.js preview can reach the API.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(v1_router)
    app.include_router(auth_router)
    app.include_router(connections_router)
    app.include_router(content_manager_router)
    return app


app = create_app()
