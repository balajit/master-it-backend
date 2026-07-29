"""Document routes aggregator.

This module preserves compatibility for imports and test patch paths.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter

from learning_platform.infrastructure.persistence.repositories.concept import ConceptRepository
from learning_platform.infrastructure.persistence.repositories.document import DocumentRepository
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.infrastructure.persistence.repositories.sequence import StudyPlanRepository

from . import documents_read, documents_write

router = APIRouter()
router.include_router(documents_write.router)
router.include_router(documents_read.router)

# Re-export classes used by tests that patch this module path.
__all__ = [
    "ConceptRepository",
    "DocumentRepository",
    "LearningUnitRepository",
    "Path",
    "StudyPlanRepository",
    "router",
]
