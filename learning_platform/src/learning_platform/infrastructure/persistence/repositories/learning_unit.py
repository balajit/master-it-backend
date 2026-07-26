"""Repository for learning units."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.learning_unit import LearningUnitRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.learning_unit import (
    Difficulty,
    LearningUnit,
    NodeRef,
    UnitType,
)


class LearningUnitRepository(BaseRepository[LearningUnitRow]):
    """Persists and retrieves ``LearningUnit`` instances."""

    model_class = LearningUnitRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_unit(self, unit: LearningUnit, document_id: UUID) -> UUID:
        """Serialize and persist a ``LearningUnit``.  Returns its ID."""
        row = LearningUnitRow(
            id=unit.id,
            document_id=document_id,
            unit_type=unit.unit_type.value,
            title=unit.title,
            description=unit.description,
            difficulty=unit.difficulty.value,
            estimated_study_time_minutes=unit.estimated_study_time_minutes,
            parent_id=unit.parent_id,
            learning_objectives_json=unit.learning_objectives,
            content_references_json=[r.model_dump(mode="json") for r in unit.content_references],
            definitions_json=[r.model_dump(mode="json") for r in unit.definitions],
            examples_json=[r.model_dump(mode="json") for r in unit.examples],
            figures_json=[r.model_dump(mode="json") for r in unit.figures],
            tables_json=[r.model_dump(mode="json") for r in unit.tables],
            equations_json=[r.model_dump(mode="json") for r in unit.equations],
            exercises_json=[r.model_dump(mode="json") for r in unit.exercises],
            source_node_ids_json=[str(uid) for uid in unit.source_node_ids],
            children_ids_json=[str(uid) for uid in unit.children_ids],
            prerequisite_ids_json=[str(uid) for uid in unit.prerequisite_ids],
            metadata_json=unit.metadata,
        )
        await self.save(row)
        return row.id

    async def save_all_units(self, units: list[LearningUnit], document_id: UUID) -> list[UUID]:
        """Bulk persist learning units."""
        rows = [
            LearningUnitRow(
                id=u.id,
                document_id=document_id,
                unit_type=u.unit_type.value,
                title=u.title,
                description=u.description,
                difficulty=u.difficulty.value,
                estimated_study_time_minutes=u.estimated_study_time_minutes,
                parent_id=u.parent_id,
                learning_objectives_json=u.learning_objectives,
                content_references_json=[r.model_dump(mode="json") for r in u.content_references],
                definitions_json=[r.model_dump(mode="json") for r in u.definitions],
                examples_json=[r.model_dump(mode="json") for r in u.examples],
                figures_json=[r.model_dump(mode="json") for r in u.figures],
                tables_json=[r.model_dump(mode="json") for r in u.tables],
                equations_json=[r.model_dump(mode="json") for r in u.equations],
                exercises_json=[r.model_dump(mode="json") for r in u.exercises],
                source_node_ids_json=[str(uid) for uid in u.source_node_ids],
                children_ids_json=[str(uid) for uid in u.children_ids],
                prerequisite_ids_json=[str(uid) for uid in u.prerequisite_ids],
                metadata_json=u.metadata,
            )
            for u in units
        ]
        await self.save_all(rows)
        return [r.id for r in rows]

    async def find_by_document(self, document_id: UUID) -> list[LearningUnit]:
        """Return all learning units for a given document."""
        stmt = select(LearningUnitRow).where(LearningUnitRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def find_by_type(self, document_id: UUID, unit_type: UnitType) -> list[LearningUnit]:
        """Return learning units filtered by type."""
        stmt = select(LearningUnitRow).where(
            LearningUnitRow.document_id == document_id,
            LearningUnitRow.unit_type == unit_type.value,
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete all learning units for a document."""
        from sqlalchemy import delete

        stmt = delete(LearningUnitRow).where(LearningUnitRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    def _to_domain(row: LearningUnitRow) -> LearningUnit:
        """Reconstruct a ``LearningUnit`` from a persisted row."""
        return LearningUnit(
            id=row.id,
            unit_type=UnitType(row.unit_type),
            title=row.title,
            description=row.description,
            difficulty=Difficulty(row.difficulty),
            estimated_study_time_minutes=row.estimated_study_time_minutes,
            parent_id=row.parent_id,
            learning_objectives=row.learning_objectives_json or [],
            content_references=[
                NodeRef.model_validate(r) for r in (row.content_references_json or [])
            ],
            definitions=[NodeRef.model_validate(r) for r in (row.definitions_json or [])],
            examples=[NodeRef.model_validate(r) for r in (row.examples_json or [])],
            figures=[NodeRef.model_validate(r) for r in (row.figures_json or [])],
            tables=[NodeRef.model_validate(r) for r in (row.tables_json or [])],
            equations=[NodeRef.model_validate(r) for r in (row.equations_json or [])],
            exercises=[NodeRef.model_validate(r) for r in (row.exercises_json or [])],
            source_node_ids=[UUID(uid) for uid in (row.source_node_ids_json or [])],
            children_ids=[UUID(uid) for uid in (row.children_ids_json or [])],
            prerequisite_ids=[UUID(uid) for uid in (row.prerequisite_ids_json or [])],
            metadata=row.metadata_json or {},
        )
