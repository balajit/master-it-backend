"""FastAPI application factory."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

load_dotenv()

from learning_platform.config import Settings, get_settings


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

app = create_app()
