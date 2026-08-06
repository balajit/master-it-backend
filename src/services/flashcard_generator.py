"""Generate flashcards for a lesson using the Curator agent.

``FlashCardGenerator`` loads an LP book lesson by id, extracts the text of
every page belonging to that lesson, and asks the Curator agent to pull out
key terms.  Each term/definition pair becomes a flashcard (term on the front,
definition on the back).
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any
from uuid import UUID

from learning_platform.agents.curator import CuratorAgent
from learning_platform.config import Settings
from learning_platform.infrastructure.persistence.engine import create_engine
from learning_platform.infrastructure.persistence.models.book import BookLessonRow
from learning_platform.infrastructure.persistence.repositories.book import (
    BookRepository,
)
from learning_platform.infrastructure.persistence.session import create_session_factory

logger = logging.getLogger(__name__)

_TEXT_TYPES: frozenset[str] = frozenset({"text", "heading", "code"})
_MULTILINE_TYPES: frozenset[str] = frozenset({"list", "form_area"})


class FlashCardGenerator:
    """Generate front/back flashcard pairs for a lesson via the Curator agent."""

    def __init__(
        self,
        lesson_id: UUID,
        curator: CuratorAgent,
        scope: str = "lesson",
    ) -> None:
        self._lesson_id = lesson_id
        self._curator = curator
        self._scope = scope

    @property
    def lesson_id(self) -> UUID:
        """The LP book-lesson id this generator is scoped to."""
        return self._lesson_id

    async def generate(self) -> list[dict[str, str]]:
        """Return a list of ``{"front": term, "back": definition}`` cards.

        Returns an empty list when the lesson is missing, has no extractable
        text, the Curator returns no key terms, or analysis fails.
        """
        lesson = await self._get_lesson(self._lesson_id)
        if lesson is None:
            logger.info("No LP lesson found for id %s", self._lesson_id)
            return []

        lesson_text = await self._extract_lesson_text(lesson.id)
        if not lesson_text.strip():
            logger.info("No extractable text for lesson %s", lesson.id)
            return []

        try:
            analysis: dict[str, Any] = await asyncio.to_thread(
                self._curator.analyze, lesson_text
            )
        except Exception:
            logger.exception("Curator analysis failed for lesson %s", lesson.id)
            return []

        return self._cards_from_key_terms(analysis)

    async def _get_lesson(self, lesson_id: UUID) -> BookLessonRow | None:
        """Load the LP book lesson row for *lesson_id*."""
        from sqlalchemy import select

        engine = create_engine(Settings())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                result = await session.execute(
                    select(BookLessonRow).where(BookLessonRow.id == lesson_id)
                )
                return result.scalars().first()
        finally:
            await engine.dispose()

    async def _extract_lesson_text(self, lesson_id: UUID) -> str:
        """Concatenate the text of every page belonging to *lesson_id*."""
        engine = create_engine(Settings())
        factory = create_session_factory(engine)
        try:
            async with factory() as session:
                repo = BookRepository(session)
                pages = await repo.find_pages_by_lesson(lesson_id)
        finally:
            await engine.dispose()

        return "\n".join(self._page_to_text(page) for page in pages)

    @staticmethod
    def _page_to_text(page: Any) -> str:
        """Join the textual content of every item on a single page."""
        lines: list[str] = []
        for item in page.items:
            text = FlashCardGenerator._item_to_text(item)
            if text:
                lines.append(text)
        return "\n".join(lines)

    @staticmethod
    def _item_to_text(item: Any) -> str:
        """Extract the textual content of a single content item."""
        item_type = getattr(item, "type", "")

        if item_type in _TEXT_TYPES:
            return str(getattr(item, "content", "") or "").strip()
        if item_type in _MULTILINE_TYPES:
            return "\n".join(str(value) for value in getattr(item, "items", []))
        if item_type == "table":
            lines: list[str] = []
            caption = getattr(item, "caption", None)
            if caption:
                lines.append(str(caption))
            headers = getattr(item, "headers", [])
            if headers:
                lines.append(" | ".join(str(header) for header in headers))
            lines.extend(
                " | ".join(str(cell) for cell in row)
                for row in getattr(item, "rows", [])
            )
            return "\n".join(lines).strip()
        if item_type == "equation":
            return str(getattr(item, "latex", "") or "").strip()
        if item_type == "question":
            return str(getattr(item, "content", "") or "").strip()
        if item_type == "image":
            caption = getattr(item, "caption", None)
            return str(caption).strip() if caption else ""
        return ""

    @staticmethod
    def _cards_from_key_terms(analysis: dict[str, Any]) -> list[dict[str, str]]:
        """Map Curator ``key_terms`` to front/back flashcard pairs.

        Entries without a term or definition are skipped; exact duplicates
        are dropped.
        """
        key_terms = analysis.get("key_terms", [])
        if not isinstance(key_terms, list):
            return []

        cards: list[dict[str, str]] = []
        seen: set[tuple[str, str]] = set()
        for entry in key_terms:
            if not isinstance(entry, dict):
                continue
            term = str(entry.get("term") or "").strip()
            definition = str(entry.get("definition") or "").strip()
            if not term or not definition:
                continue
            key = (term, definition)
            if key in seen:
                continue
            seen.add(key)
            cards.append({"front": term, "back": definition})
        return cards
