"""Repository for canonical documents."""

from __future__ import annotations

from uuid import UUID

from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.document import CanonicalDocumentRow
from learning_platform.infrastructure.persistence.repositories.base import BaseRepository
from learning_platform.models.document import CanonicalDocument, DocumentMetadata, DocumentNode

_NODE_LIST_ADAPTER: TypeAdapter[list[DocumentNode]] = TypeAdapter(list[DocumentNode])


class DocumentRepository(BaseRepository[CanonicalDocumentRow]):
    """Persists and retrieves ``CanonicalDocument`` instances."""

    model_class = CanonicalDocumentRow

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def save_document(
        self,
        doc: CanonicalDocument,
        doc_id: UUID | None = None,
        owner_sub: str | None = None,
    ) -> UUID:
        """Serialize and persist a ``CanonicalDocument``.  Returns its ID.

        When *doc_id* is provided it is used as the primary key; otherwise
        the first document node's ID is used.

        If a document row already exists for the same ID, it is updated in
        place so reruns do not hit primary-key collisions.
        """
        if doc_id is None:
            doc_id = doc.nodes[0].id if doc.nodes else UUID(int=0)

        existing = await self.find_by_id(doc_id)
        if existing is not None:
            existing.source = doc.source
            existing.title = doc.title
            if owner_sub is not None:
                existing.owner_sub = owner_sub
            existing.metadata_json = doc.metadata.model_dump()
            existing.nodes_json = self._serialize_nodes(doc.nodes)
            await self.save(existing)
            return existing.id

        row = CanonicalDocumentRow(
            id=doc_id,
            source=doc.source,
            title=doc.title,
            owner_sub=owner_sub,
            metadata_json=doc.metadata.model_dump(),
            nodes_json=self._serialize_nodes(doc.nodes),
        )
        await self.save(row)
        return row.id

    async def find_document(self, doc_id: UUID) -> CanonicalDocument | None:
        """Load a ``CanonicalDocument`` by ID."""
        row = await self.find_by_id(doc_id)
        if row is None:
            return None
        return self._to_domain(row)

    async def find_owner_sub(self, doc_id: UUID) -> str | None:
        """Return owner subject for a document, or ``None`` if not owned/public."""
        stmt = select(CanonicalDocumentRow.owner_sub).where(CanonicalDocumentRow.id == doc_id)
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def delete_by_id(self, doc_id: UUID) -> bool:
        """Delete a document by ID.  Returns True if found."""
        row = await self.find_by_id(doc_id)
        if row is None:
            return False
        await self.delete(row)
        return True

    # ── internal ─────────────────────────────────────────────────────────

    @staticmethod
    def _serialize_nodes(nodes: list[DocumentNode]) -> list[dict[str, object]]:
        """Recursively serialize the node tree to a JSON-safe list."""
        result: list[dict[str, object]] = []
        for node in nodes:
            d = node.model_dump(mode="json")
            result.append(d)
        return result

    @staticmethod
    def _to_domain(row: CanonicalDocumentRow) -> CanonicalDocument:
        """Reconstruct a ``CanonicalDocument`` from a persisted row."""
        nodes = _NODE_LIST_ADAPTER.validate_python(row.nodes_json or [])
        meta = DocumentMetadata.model_validate(row.metadata_json or {})
        doc = CanonicalDocument(
            source=row.source,
            title=row.title,
            metadata=meta,
            nodes=nodes,
        )
        doc.rebuild_index()
        return doc
