"""Pipeline package — public re-exports.

Import stage Protocols and the orchestrator from here.
"""

from __future__ import annotations

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
from learning_platform.pipeline.event_bus import EventBus, SimpleEventBus
from learning_platform.pipeline.events import EventType, PipelineEvent
from learning_platform.pipeline.orchestrator import PipelineOrchestrator, PipelineResult
from learning_platform.pipeline.plugins import PluginRegistry
from learning_platform.pipeline.retry import RetryPolicy, with_retry

__all__ = [
    # Stage Protocols
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
    # Events
    "EventBus",
    "EventType",
    "PipelineEvent",
    "SimpleEventBus",
    # Plugins
    "PluginRegistry",
    # Retry
    "RetryPolicy",
    "with_retry",
]
