"""FastAPI dependency injection — wires concrete implementations to Protocols."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from learning_platform.config import Settings, get_settings
from learning_platform.infrastructure.persistence.engine import create_engine
from learning_platform.infrastructure.persistence.repositories.annotation import (
    AnnotationRepository,
)
from learning_platform.infrastructure.persistence.repositories.concept import ConceptRepository
from learning_platform.infrastructure.persistence.repositories.document import DocumentRepository
from learning_platform.infrastructure.persistence.repositories.knowledge_graph import (
    KnowledgeGraphRepository,
)
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.infrastructure.persistence.repositories.sequence import StudyPlanRepository
from learning_platform.pipeline.base import AbstractParser
from learning_platform.pipeline.event_bus import SimpleEventBus
from learning_platform.pipeline.orchestrator import PipelineOrchestrator
from learning_platform.pipeline.plugins import PluginRegistry
from learning_platform.poller import FilePoller
from learning_platform.stages.concept_extractor import ConceptExtractor
from learning_platform.stages.enricher.engine import EnrichmentEngine
from learning_platform.stages.enricher.semantic import SemanticEnricher
from learning_platform.stages.graph_builder.graph import NetworkxGraphBuilder
from learning_platform.stages.normalizer.structural import StructuralNormalizer
from learning_platform.stages.parser2 import Parser2Adapter
from learning_platform.stages.sequence_builder.sequencer import TopologicalSequenceBuilder
from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

_LOG = logging.getLogger(__name__)

# ── Module-level singletons ─────────────────────────────────────────────────

_engine: Any = None
_session_factory: async_sessionmaker[AsyncSession] | None = None
_upload_dir: Path | None = None
_orchestrator: PipelineOrchestrator | None = None


def _ensure_upload_dir(settings: Settings) -> Path:
    """Return the upload directory, creating it if needed."""
    global _upload_dir
    if _upload_dir is None:
        _upload_dir = Path(settings.upload_path)
        _upload_dir.mkdir(parents=True, exist_ok=True)
    return _upload_dir


# ── Settings ────────────────────────────────────────────────────────────────


def get_settings_dependency(request: Request) -> Settings:
    """FastAPI dependency for application settings."""
    app_settings = getattr(request.app.state, "settings", None)
    if isinstance(app_settings, Settings):
        return app_settings
    return get_settings()


# ── Database ────────────────────────────────────────────────────────────────


def get_engine(settings: Settings | None = None) -> Any:
    """Return the async engine (created once)."""
    global _engine
    if _engine is None:
        settings = settings or get_settings()
        _engine = create_engine(settings)
    return _engine


def get_session_factory(settings: Settings | None = None) -> async_sessionmaker[AsyncSession]:
    """Return the session factory (created once)."""
    global _session_factory
    if _session_factory is None:
        from learning_platform.infrastructure.persistence.session import create_session_factory

        engine = get_engine(settings)
        _session_factory = create_session_factory(engine)
    return _session_factory


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Provide an async session per request."""
    factory = get_session_factory()
    async with factory() as session:
        yield session


# ── Pipeline ────────────────────────────────────────────────────────────────


def _create_parser(settings: Settings) -> AbstractParser:
    """Create the parser based on the parser_backend setting.

    Returns Parser2Adapter.
    """
    backend = settings.parser_backend.strip().lower()

    if backend != "parser2":
        _LOG.info("Unknown parser_backend '%s'; defaulting to Parser2Adapter", backend)
    else:
        _LOG.info("Using Parser2Adapter (parser_backend='parser2')")
    return Parser2Adapter()


def get_pipeline_orchestrator() -> PipelineOrchestrator:
    """Return the pipeline orchestrator singleton (built once per process).

    The parser backend is selected based on the ``parser_backend`` setting:
    - ``"parser2"`` (default): Uses ``Parser2Adapter`` with direct mapping

    Constructing the orchestrator is expensive: the parser initialises
    the document converter, all stage objects are created, and the
    plugin registry is built.  Creating a new instance per request wastes
    time and memory.  The singleton is process-local and therefore safe for
    single-worker deployments.
    """
    global _orchestrator
    if _orchestrator is None:
        settings = get_settings()
        parser = _create_parser(settings)
        _orchestrator = PipelineOrchestrator(
            parser=parser,
            normalizer=StructuralNormalizer(),
            enricher=SemanticEnricher(
                engine=EnrichmentEngine.from_settings(settings),
            ),
            unit_builder=LearningUnitBuilder(),
            concept_extractor=ConceptExtractor.from_settings(settings),
            graph_builder=NetworkxGraphBuilder(),
            sequence_builder=TopologicalSequenceBuilder(),
            event_bus=SimpleEventBus(),
            plugin_registry=PluginRegistry(),
        )
        _LOG.info("PipelineOrchestrator singleton created")
    return _orchestrator


# ── Repositories ────────────────────────────────────────────────────────────


def get_document_repository(session: AsyncSession = Any) -> DocumentRepository:
    """Provide a DocumentRepository."""
    return DocumentRepository(session)


def get_learning_unit_repository(session: AsyncSession = Any) -> LearningUnitRepository:
    """Provide a LearningUnitRepository."""
    return LearningUnitRepository(session)


def get_annotation_repository(session: AsyncSession = Any) -> AnnotationRepository:
    """Provide an AnnotationRepository."""
    return AnnotationRepository(session)


def get_concept_repository(session: AsyncSession = Any) -> ConceptRepository:
    """Provide a ConceptRepository."""
    return ConceptRepository(session)


def get_knowledge_graph_repository(session: AsyncSession = Any) -> KnowledgeGraphRepository:
    """Provide a KnowledgeGraphRepository."""
    return KnowledgeGraphRepository(session)


def get_study_plan_repository(session: AsyncSession = Any) -> StudyPlanRepository:
    """Provide a StudyPlanRepository."""
    return StudyPlanRepository(session)


# ── Upload directory ────────────────────────────────────────────────────────


def get_upload_dir(settings: Settings | None = None) -> Path:
    """Return the upload directory path."""
    settings = settings or get_settings()
    return _ensure_upload_dir(settings)


# ── Poller ──────────────────────────────────────────────────────────────────


def get_poller() -> FilePoller | None:
    """Return the FilePoller instance if one is running, or ``None``."""
    from learning_platform.api.app import get_poller_instance

    return get_poller_instance()
