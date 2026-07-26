"""FastAPI application factory."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from learning_platform.config import Settings, get_settings

_app_instance: FastAPI | None = None


def create_app(settings: Settings | None = None) -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = settings or get_settings()

    app = FastAPI(
        title="Learning Platform API",
        description=(
            "Document processing, knowledge graph construction, and adaptive learning pipeline."
        ),
        version="0.1.0",
        debug=settings.debug,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    from learning_platform.api.routes import documents, health

    app.include_router(health.router)
    app.include_router(
        documents.router,
        prefix="/api/documents",
        tags=["documents"],
    )

    return app


def get_lp_app() -> FastAPI:
    """Return the LP FastAPI app singleton.

    Always returns the same instance so that the shared ``pipeline_cache``
    is never split across multiple app objects — regardless of whether the
    caller is ``src/main.py`` (mounting) or any other integration point.
    """
    global _app_instance
    if _app_instance is None:
        _app_instance = create_app()
    return _app_instance


app = get_lp_app()
