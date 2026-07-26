"""Summary models — document and section summaries at various levels.

A ``DocumentSummarizer`` plugin produces ``Summary`` instances after the
pipeline has generated learning units.  Summaries can target the full
document, individual sections, or specific learning units.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SummaryLevel(StrEnum):
    """Granularity of a summary."""

    DOCUMENT = "document"
    SECTION = "section"
    UNIT = "unit"
    CONCEPT = "concept"


class Summary(BaseModel):
    """A textual summary at a specific granularity level."""

    id: UUID = Field(default_factory=uuid4)
    level: SummaryLevel
    title: str
    text: str
    source_document_id: UUID | None = None
    source_unit_id: UUID | None = None
    source_section_path: list[str] = Field(default_factory=list)
    key_points: list[str] = Field(default_factory=list)
    word_count: int = 0
    metadata: dict[str, str] = Field(default_factory=dict)

    def model_post_init(self, _context: object) -> None:
        """Compute word_count from text if not set."""
        if self.word_count == 0 and self.text:
            object.__setattr__(self, "word_count", len(self.text.split()))
