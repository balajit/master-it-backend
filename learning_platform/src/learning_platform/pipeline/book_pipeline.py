"""Pipeline 2 — Book Assembly Pipeline.

Reads persisted Pipeline 1 artifacts (LearningUnits, CanonicalDocument)
for a given document_id, assembles a CanonicalBook, and persists it.

This pipeline is independent of Pipeline 1 and can be re-run when the
book assembly logic changes without re-parsing the original document.
"""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from learning_platform.infrastructure.persistence.repositories.book import (
    BookRepository,
)
from learning_platform.infrastructure.persistence.repositories.document import (
    DocumentRepository,
)
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.models.book import CanonicalBook
from learning_platform.models.document import CanonicalDocument
from learning_platform.models.learning_unit import LearningUnit
from learning_platform.stages.book_assembler.assembler import BookAssembler

_LOG = logging.getLogger(__name__)


class BookPipeline:
    """Assembles and persists a CanonicalBook for a given document."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session
        self._assembler = BookAssembler()
        self._book_repo = BookRepository(session)
        self._doc_repo = DocumentRepository(session)
        self._unit_repo = LearningUnitRepository(session)

    async def run(self, document_id: UUID) -> CanonicalBook:
        """Run the book assembly pipeline for a document.

        Raises:
            ValueError: if the document or its units are not found.
        """
        _LOG.info("BookPipeline: assembling book for document %s", document_id)

        document: CanonicalDocument | None = await self._doc_repo.find_document(document_id)
        if document is None:
            raise ValueError(f"Document {document_id} not found in LP database")

        units: list[LearningUnit] = await self._unit_repo.find_by_document(document_id)
        _LOG.info(
            "BookPipeline: loaded %d learning units for document %s",
            len(units),
            document_id,
        )

        book = self._assembler.assemble(units, document)

        # Use model_copy for Pydantic v2 to stamp the correct document_id
        book = book.model_copy(update={"document_id": document_id})

        await self._book_repo.save_book(book)
        _LOG.info(
            "BookPipeline: saved book for document %s — %d chapters",
            document_id,
            len(book.chapters),
        )
        return book
