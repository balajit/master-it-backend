"""Enrichment detectors — each scans the document for a specific pattern."""

from learning_platform.stages.enricher.detectors.callout import CalloutDetector
from learning_platform.stages.enricher.detectors.cross_reference import CrossReferenceDetector
from learning_platform.stages.enricher.detectors.definition import DefinitionDetector
from learning_platform.stages.enricher.detectors.equation_association import (
    EquationAssociationDetector,
)
from learning_platform.stages.enricher.detectors.example import ExampleDetector
from learning_platform.stages.enricher.detectors.exercise import ExerciseDetector
from learning_platform.stages.enricher.detectors.figure_association import (
    FigureAssociationDetector,
)
from learning_platform.stages.enricher.detectors.key_term import KeyTermDetector
from learning_platform.stages.enricher.detectors.objective import ObjectiveDetector
from learning_platform.stages.enricher.detectors.summary import SummaryDetector

__all__ = [
    "CalloutDetector",
    "CrossReferenceDetector",
    "DefinitionDetector",
    "EquationAssociationDetector",
    "ExampleDetector",
    "ExerciseDetector",
    "FigureAssociationDetector",
    "KeyTermDetector",
    "ObjectiveDetector",
    "SummaryDetector",
]
