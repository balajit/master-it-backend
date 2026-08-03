"""learning_platform — public API surface.

Import from here, not from internal sub-modules.  Paths inside
``stages/``, ``infrastructure/``, and ``api/`` are implementation
details and may change without notice.
"""

from __future__ import annotations

# ── Agentic operations ───────────────────────────────────────────────────────
from learning_platform.agentic_ops import (
    AgenticOpsSettings,
    DatabaseEntriesReportPage,
    McpReportClient,
    ReportScope,
    RuleSet,
    TriageAgent,
    TriageFinding,
    TriageResult,
    TriageService,
    build_default_rule_set,
)

# ── Cache ────────────────────────────────────────────────────────────────────
from learning_platform.cache import PipelineCache, pipeline_cache

# ── Core domain models ───────────────────────────────────────────────────────
from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import Concept, ConceptMap, ConceptRelationship
from learning_platform.models.document import CanonicalDocument, DocumentNode
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit, NodeRef
from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.models.sequence import StudyPlan

# ── Pipeline contracts (Protocols) ───────────────────────────────────────────
from learning_platform.pipeline.base import (
    AbstractParser,
    ConceptExtractor,
    Detector,
    DocumentSummarizer,
    KnowledgeGraphBuilder,
    LearningSequenceBuilder,
    LearningUnitBuilder,
    QuizGenerator,
    SearchIndex,
    SemanticEnricher,
    StructuralNormalizer,
    VectorIndexer,
)

# ── Orchestrator and result ──────────────────────────────────────────────────
from learning_platform.pipeline.orchestrator import PipelineOrchestrator, PipelineResult
from learning_platform.presentation.mappers.configuration import (
    MappingConfiguration,
    create_default_config,
)
from learning_platform.presentation.mappers.context import ProgressContext
from learning_platform.presentation.mappers.learning_experience import (
    PipelineOutput,
    create_learning_experience,
)

# ── Presentation layer ───────────────────────────────────────────────────────
from learning_platform.presentation.models import StudyExperience

# ── Service façade (for host-app integration without HTTP proxy) ──────────────
from learning_platform.service import LearningPlatformService, get_service, stable_doc_id

__all__ = [
    # Agentic operations
    "AgenticOpsSettings",
    "DatabaseEntriesReportPage",
    "McpReportClient",
    "ReportScope",
    "RuleSet",
    "TriageAgent",
    "TriageFinding",
    "TriageResult",
    "TriageService",
    "build_default_rule_set",
    # Protocols
    "AbstractParser",
    "ConceptExtractor",
    "Detector",
    "DocumentSummarizer",
    "KnowledgeGraphBuilder",
    "LearningSequenceBuilder",
    "LearningUnitBuilder",
    "QuizGenerator",
    "SearchIndex",
    "SemanticEnricher",
    "StructuralNormalizer",
    "VectorIndexer",
    # Orchestrator
    "PipelineOrchestrator",
    "PipelineResult",
    # Domain models
    "Annotation",
    "CanonicalDocument",
    "Concept",
    "ConceptMap",
    "ConceptRelationship",
    "DocumentNode",
    "KnowledgeGraph",
    "LearningUnit",
    "NodeRef",
    "PageContext",
    "StudyPlan",
    "build_page_contexts",
    # Presentation
    "MappingConfiguration",
    "PipelineOutput",
    "ProgressContext",
    "StudyExperience",
    "create_default_config",
    "create_learning_experience",
    # Cache
    "PipelineCache",
    "pipeline_cache",
    # Service façade
    "LearningPlatformService",
    "get_service",
    "stable_doc_id",
]
