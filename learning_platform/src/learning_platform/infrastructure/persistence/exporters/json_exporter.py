"""JSON exporter — serializes pipeline output to JSON files."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learning_platform.models.annotation import Annotation
    from learning_platform.models.concept import ConceptMap
    from learning_platform.models.document import CanonicalDocument
    from learning_platform.models.knowledge_graph import KnowledgeGraph
    from learning_platform.models.learning_unit import LearningUnit
    from learning_platform.models.sequence import StudyPlan


class JsonExporter:
    """Exports pipeline output entities to JSON files.

    Each ``export_*`` method writes a single JSON file to the output
    directory.  The ``export_all`` convenience method writes everything.
    """

    def __init__(self, output_dir: str | Path) -> None:
        self._output_dir = Path(output_dir)

    def export_all(
        self,
        document: CanonicalDocument,
        units: list[LearningUnit],
        annotations: list[Annotation],
        concepts: ConceptMap,
        graph: KnowledgeGraph,
        plan: StudyPlan,
    ) -> list[Path]:
        """Export all entities and return the list of written file paths."""
        paths: list[Path] = []
        paths.append(self.export_document(document))
        paths.append(self.export_units(units))
        paths.append(self.export_annotations(annotations))
        paths.append(self.export_concepts(concepts))
        paths.append(self.export_graph(graph))
        paths.append(self.export_study_plan(plan))
        return paths

    def export_document(self, doc: CanonicalDocument) -> Path:
        path = self._output_dir / "document.json"
        path.write_text(json.dumps(doc.model_dump(mode="json"), indent=2, default=str))
        return path

    def export_units(self, units: list[LearningUnit]) -> Path:
        path = self._output_dir / "learning_units.json"
        data = [u.model_dump(mode="json") for u in units]
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def export_annotations(self, annotations: list[Annotation]) -> Path:
        path = self._output_dir / "annotations.json"
        data = [a.model_dump(mode="json") for a in annotations]
        path.write_text(json.dumps(data, indent=2, default=str))
        return path

    def export_concepts(self, concepts: ConceptMap) -> Path:
        path = self._output_dir / "concepts.json"
        path.write_text(json.dumps(concepts.model_dump(mode="json"), indent=2, default=str))
        return path

    def export_graph(self, graph: KnowledgeGraph) -> Path:
        path = self._output_dir / "knowledge_graph.json"
        path.write_text(json.dumps(graph.model_dump(mode="json"), indent=2, default=str))
        return path

    def export_study_plan(self, plan: StudyPlan) -> Path:
        path = self._output_dir / "study_plan.json"
        path.write_text(json.dumps(plan.model_dump(mode="json"), indent=2, default=str))
        return path
