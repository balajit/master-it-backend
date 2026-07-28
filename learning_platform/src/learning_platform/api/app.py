"""FastAPI application factory."""

from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI

from learning_platform.config import Settings, get_settings
from learning_platform.poller import FilePoller

load_dotenv()

_app_instance: FastAPI | None = None
_poller: FilePoller | None = None


async def start_poller() -> None:
    """Start the file poller if not already running."""
    global _poller
    if _poller is not None:
        return
    from learning_platform.api.deps import get_session_factory

    settings = get_settings()
    factory = get_session_factory()
    _poller = FilePoller(upload_path=settings.upload_path, session_factory=factory)
    await _poller.start()


async def stop_poller() -> None:
    """Stop the file poller if running."""
    global _poller
    if _poller is not None:
        await _poller.stop()
        _poller = None


def get_poller_instance() -> FilePoller | None:
    """Return the poller singleton, or ``None`` if not started."""
    return _poller


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

    from learning_platform.api.routes import courses, documents, health

    app.include_router(health.router)
    app.include_router(
        documents.router,
        prefix="/api/documents",
        tags=["documents"],
    )
    app.include_router(
        courses.router,
        prefix="/api/courses",
        tags=["courses"],
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
