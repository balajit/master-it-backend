"""Models package — public re-exports.

Import domain models from here rather than from individual sub-modules.
"""

from __future__ import annotations

from learning_platform.models.annotation import Annotation
from learning_platform.models.book import (
    BookChapter,
    BookLesson,
    BookPage,
    CanonicalBook,
    CodeItem,
    ContentItem,
    EquationItem,
    FormAreaItem,
    HeadingItem,
    ImageItem,
    ListItem,
    QuestionItem,
    TableItem,
    TextItem,
)
from learning_platform.models.concept import Concept, ConceptMap, ConceptRelationship
from learning_platform.models.document import CanonicalDocument, DocumentNode
from learning_platform.models.knowledge_graph import GraphEdge, GraphNode, KnowledgeGraph
from learning_platform.models.learning_unit import LearningUnit, NodeRef
from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.models.quiz import Quiz
from learning_platform.models.sequence import StudyPlan
from learning_platform.models.summary import Summary

__all__ = [
    "Annotation",
    "BookChapter",
    "BookLesson",
    "BookPage",
    "CanonicalBook",
    "CanonicalDocument",
    "CodeItem",
    "Concept",
    "ConceptMap",
    "ConceptRelationship",
    "ContentItem",
    "DocumentNode",
    "EquationItem",
    "FormAreaItem",
    "GraphEdge",
    "GraphNode",
    "HeadingItem",
    "ImageItem",
    "KnowledgeGraph",
    "LearningUnit",
    "ListItem",
    "NodeRef",
    "PageContext",
    "QuestionItem",
    "Quiz",
    "StudyPlan",
    "Summary",
    "TableItem",
    "TextItem",
    "build_page_contexts",
]
