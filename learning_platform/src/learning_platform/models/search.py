"""Search models — queries, filters, and search results.

A ``SearchIndex`` plugin accepts ``SearchQuery`` instances and returns
ranked ``SearchResult`` lists.  Filters narrow results by document,
unit, concept, or content type.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SearchFilter(BaseModel):
    """A single filter criterion for narrowing search results."""

    field: str
    operator: str = "eq"
    value: str = ""


class SearchQuery(BaseModel):
    """A structured search request."""

    text: str
    filters: list[SearchFilter] = Field(default_factory=list)
    limit: int = 10
    offset: int = 0
    include_highlights: bool = True


class SearchResult(BaseModel):
    """A single search result with relevance scoring."""

    id: UUID = Field(default_factory=uuid4)
    document_id: UUID | None = None
    unit_id: UUID | None = None
    concept_name: str = ""
    title: str = ""
    snippet: str = ""
    highlights: list[str] = Field(default_factory=list)
    score: float = 0.0
    source_type: str = ""
    metadata: dict[str, str] = Field(default_factory=dict)
