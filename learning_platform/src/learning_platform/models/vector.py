"""Vector models — documents and stores for embedding-based search.

A ``VectorIndexer`` plugin indexes ``VectorDocument`` instances into a
``VectorStore`` and supports similarity queries.  The store can be
backed by FAISS, Chroma, pgvector, or any other vector database.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class VectorDocument(BaseModel):
    """A document with its embedding vector, ready for indexing."""

    id: UUID = Field(default_factory=uuid4)
    text: str
    embedding: list[float] = Field(default_factory=list)
    document_id: UUID | None = None
    unit_id: UUID | None = None
    chunk_index: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)


class VectorStore(BaseModel):
    """A collection of indexed vector documents."""

    id: UUID = Field(default_factory=uuid4)
    name: str
    documents: list[VectorDocument] = Field(default_factory=list)
    dimension: int = 0
    index_type: str = "flat"
    metadata: dict[str, str] = Field(default_factory=dict)

    @property
    def count(self) -> int:
        """Number of documents in the store."""
        return len(self.documents)
