"""Repository for annotations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import select

if TYPE_CHECKING:
    from uuid import UUID

    from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.annotation import AnnotationRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.annotation import (
    Annotation,
    CalloutAnnotation,
    CrossReferenceAnnotation,
    DefinitionAnnotation,
    EquationAssociationAnnotation,
    ExampleAnnotation,
    ExerciseAnnotation,
    FigureAssociationAnnotation,
    KeyTermAnnotation,
    ObjectiveAnnotation,
    SummaryAnnotation,
)

_ANNOTATION_MAP: dict[str, type] = {
    "definition": DefinitionAnnotation,
    "example": ExampleAnnotation,
    "exercise": ExerciseAnnotation,
    "objective": ObjectiveAnnotation,
    "summary": SummaryAnnotation,
    "callout": CalloutAnnotation,
    "key_term": KeyTermAnnotation,
    "cross_reference": CrossReferenceAnnotation,
    "figure_association": FigureAssociationAnnotation,
    "equation_association": EquationAssociationAnnotation,
}


class AnnotationRepository(BaseRepository[AnnotationRow]):
    """Persists and retrieves ``Annotation`` instances."""

    model_class = AnnotationRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_annotation(self, annotation: Annotation, document_id: UUID) -> UUID:
        """Serialize and persist an ``Annotation``.  Returns its ID."""
        ann_id = annotation.id
        ann_type = annotation.type
        payload = annotation.model_dump(mode="json")
        del payload["id"]
        del payload["type"]
        del payload["node_id"]
        del payload["confidence"]
        del payload["detector"]

        row = AnnotationRow(
            id=ann_id,
            document_id=document_id,
            type=ann_type,
            node_id=annotation.node_id,
            confidence=annotation.confidence,
            detector=annotation.detector,
            payload=payload,
        )
        await self.save(row)
        return row.id

    async def save_all_annotations(
        self, annotations: list[Annotation], document_id: UUID
    ) -> list[UUID]:
        """Bulk persist annotations."""
        rows = []
        for ann in annotations:
            payload = ann.model_dump(mode="json")
            del payload["id"]
            del payload["type"]
            del payload["node_id"]
            del payload["confidence"]
            del payload["detector"]
            rows.append(
                AnnotationRow(
                    id=ann.id,
                    document_id=document_id,
                    type=ann.type,
                    node_id=ann.node_id,
                    confidence=ann.confidence,
                    detector=ann.detector,
                    payload=payload,
                )
            )
        await self.save_all(rows)
        return [r.id for r in rows]

    async def find_by_document(self, document_id: UUID) -> list[Annotation]:
        """Return all annotations for a given document."""
        stmt = select(AnnotationRow).where(AnnotationRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete all annotations for a document."""
        from sqlalchemy import delete

        stmt = delete(AnnotationRow).where(AnnotationRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    def _to_domain(row: AnnotationRow) -> Annotation:
        """Reconstruct an ``Annotation`` from a persisted row."""
        ann_cls = _ANNOTATION_MAP.get(row.type)
        if ann_cls is None:
            msg = f"Unknown annotation type: {row.type}"
            raise ValueError(msg)
        data = row.payload or {}
        data["id"] = row.id
        data["type"] = row.type
        data["node_id"] = row.node_id
        data["confidence"] = row.confidence
        data["detector"] = row.detector
        return ann_cls.model_validate(data)  # type: ignore[no-any-return]
