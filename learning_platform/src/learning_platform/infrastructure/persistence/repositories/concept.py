"""Repository for concepts and concept relationships."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.concept import (
    ConceptRelationshipRow,
    ConceptRow,
)
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.concept import (
    Concept,
    ConceptCategory,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)


class ConceptRepository(BaseRepository[ConceptRow]):
    """Persists and retrieves ``ConceptMap`` data."""

    model_class = ConceptRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)
        self._rel_repo = ConceptRelationshipRepository(session)

    async def save_concept_map(self, concept_map: ConceptMap, document_id: UUID) -> None:
        """Persist all concepts and relationships in a ``ConceptMap``."""
        for concept in concept_map.concepts:
            await self._save_concept(concept, document_id)
        for rel in concept_map.relationships:
            await self._rel_repo._save_relationship(rel, document_id)

    async def _save_concept(self, concept: Concept, document_id: UUID) -> UUID:
        row = ConceptRow(
            id=concept.id,
            document_id=document_id,
            name=concept.name,
            category=concept.category.value,
            importance=concept.importance,
            mention_count=concept.mention_count,
            aliases_json=concept.aliases,
            source_node_ids_json=[str(uid) for uid in concept.source_node_ids],
            source_unit_ids_json=[str(uid) for uid in concept.source_unit_ids],
            metadata_json=concept.metadata,
        )
        await self.save(row)
        return row.id

    async def find_by_document(self, document_id: UUID) -> ConceptMap:
        """Load all concepts and relationships for a document as a ``ConceptMap``."""
        stmt = select(ConceptRow).where(ConceptRow.document_id == document_id)
        result = await self._session.execute(stmt)
        concepts = [self._to_concept(r) for r in result.scalars().all()]

        rels = await self._rel_repo.find_by_document(document_id)
        return ConceptMap(concepts=concepts, relationships=rels)

    async def delete_by_document(self, document_id: UUID) -> int:
        """Delete all concepts for a document."""
        from sqlalchemy import delete

        stmt = delete(ConceptRow).where(ConceptRow.document_id == document_id)
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    def _to_concept(row: ConceptRow) -> Concept:
        return Concept(
            id=row.id,
            name=row.name,
            category=ConceptCategory(row.category),
            importance=row.importance,
            mention_count=row.mention_count,
            aliases=row.aliases_json or [],
            source_node_ids=[UUID(u) for u in (row.source_node_ids_json or [])],
            source_unit_ids=[UUID(u) for u in (row.source_unit_ids_json or [])],
            metadata=row.metadata_json or {},
        )


class ConceptRelationshipRepository(BaseRepository[ConceptRelationshipRow]):
    """Persists and retrieves concept-to-concept relationships."""

    model_class = ConceptRelationshipRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def _save_relationship(self, rel: ConceptRelationship, document_id: UUID) -> UUID:
        row = ConceptRelationshipRow(
            document_id=document_id,
            source_concept_id=rel.source_id,
            target_concept_id=rel.target_id,
            relation_type=rel.relation_type.value,
            weight=rel.weight,
            metadata_json=rel.metadata,
        )
        await self.save(row)
        return row.id

    async def find_by_document(self, document_id: UUID) -> list[ConceptRelationship]:
        stmt = select(ConceptRelationshipRow).where(
            ConceptRelationshipRow.document_id == document_id
        )
        result = await self._session.execute(stmt)
        return [self._to_domain(r) for r in result.scalars().all()]

    async def delete_by_document(self, document_id: UUID) -> int:
        from sqlalchemy import delete

        stmt = delete(ConceptRelationshipRow).where(
            ConceptRelationshipRow.document_id == document_id
        )
        result = await self._session.execute(stmt)
        return result.rowcount  # type: ignore[return-value]

    @staticmethod
    def _to_domain(row: ConceptRelationshipRow) -> ConceptRelationship:
        return ConceptRelationship(
            source_id=row.source_concept_id,
            target_id=row.target_concept_id,
            relation_type=RelationType(row.relation_type),
            weight=row.weight,
            metadata=row.metadata_json or {},
        )
