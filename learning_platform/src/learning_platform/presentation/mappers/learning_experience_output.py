"""Input model used by the learning experience mapper."""

from __future__ import annotations

from dataclasses import dataclass, field

from learning_platform.models.annotation import Annotation
from learning_platform.models.concept import ConceptMap
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.knowledge_graph import KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit
from learning_platform.models.page_context import PageContext
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import StudyPlan


@dataclass(frozen=True)
class PipelineOutput:
    """Aggregated output from the learning pipeline."""

    document: CanonicalDocument
    learning_units: list[LearningUnit]
    annotations: list[Annotation]
    concept_map: ConceptMap
    knowledge_graph: KnowledgeGraph
    study_plan: StudyPlan
    quizzes: list[Quiz]
    pages: list[PageContext] = field(default_factory=list)
