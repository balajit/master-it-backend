"""Repository for document node images."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.models.document_image import DocumentImageRow
from learning_platform.models.document import DocumentNode, Figure

_LOG = logging.getLogger(__name__)


def _walk_nodes(nodes: list[DocumentNode]):
    """Yield every node in the tree via depth-first traversal."""
    for node in nodes:
        yield node
        yield from _walk_nodes(node.children)


class DocumentImageRepository:
    """Persists and retrieves binary image data for Figure document nodes."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_for_document(
        self,
        doc_id: UUID,
        nodes: list[DocumentNode],
    ) -> int:
        """Walk *nodes*, insert/update a ``DocumentImageRow`` for each Figure with image data.

        Returns the number of rows upserted.
        """
        count = 0
        for node in _walk_nodes(nodes):
            if not isinstance(node.content, Figure):
                continue
            figure = node.content
            if figure.image_base64 is None:
                continue

            existing = await self.find_by_node_id(node.id)
            if existing is not None:
                existing.image_data = figure.image_base64
                existing.image_format = (figure.format or "PNG").upper()
                self._session.add(existing)
            else:
                row = DocumentImageRow(
                    document_id=doc_id,
                    node_id=node.id,
                    image_format=(figure.format or "PNG").upper(),
                    image_data=figure.image_base64,
                )
                self._session.add(row)

            count += 1

        if count:
            await self._session.flush()
            _LOG.debug(
                "DocumentImageRepository: upserted %d image row(s) for document %s",
                count,
                doc_id,
            )
        return count

    async def find_by_node_id(self, node_id: UUID) -> DocumentImageRow | None:
        """Return the image row for a specific document node, or ``None``."""
        stmt = select(DocumentImageRow).where(DocumentImageRow.node_id == node_id)
        result = await self._session.execute(stmt)
        return result.scalars().first()

    async def find_all_for_document(self, doc_id: UUID) -> dict[UUID, DocumentImageRow]:
        """Return a mapping of node_id → DocumentImageRow for all images in a document.

        Used to hydrate ``Figure.image_base64`` on document nodes loaded from the DB
        before passing them to the book assembler.
        """
        stmt = select(DocumentImageRow).where(DocumentImageRow.document_id == doc_id)
        result = await self._session.execute(stmt)
        rows = result.scalars().all()
        return {row.node_id: row for row in rows}

    async def hydrate_document_images(self, doc_id: UUID, nodes: list[DocumentNode]) -> int:
        """Populate ``Figure.image_base64`` on all figure nodes from persisted image rows.

        This is the inverse of ``DocumentRepository._serialize_nodes`` — it restores
        the image bytes that were stripped before DB persistence so that the
        ``BookAssembler`` can produce populated ``ImageItem.data`` values.

        Returns the number of figure nodes hydrated.
        """
        image_map = await self.find_all_for_document(doc_id)
        if not image_map:
            return 0

        count = 0
        for node in _walk_nodes(nodes):
            if not isinstance(node.content, Figure):
                continue
            row = image_map.get(node.id)
            if row is None:
                continue
            # Assign raw bytes — ImageBytes validator accepts bytes directly
            node.content.image_base64 = row.image_data
            count += 1

        _LOG.debug(
            "DocumentImageRepository: hydrated %d figure node(s) for document %s",
            count,
            doc_id,
        )
        return count
