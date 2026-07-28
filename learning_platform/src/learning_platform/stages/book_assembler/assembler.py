"""Book Assembler — converts pipeline LearningUnits into a CanonicalBook.

Assembly rules:
  - UnitType.MODULE or UnitType.COURSE → BookChapter
  - UnitType.LESSON or UnitType.TOPIC  → BookLesson under nearest parent chapter
  - Each lesson's source_node_ids are grouped by DocumentNode.page → BookPage
  - Each DocumentNode on a page becomes a typed ContentItem

Fallback (no chapter-level units):
  - All lessons are wrapped in a single synthetic chapter titled after the document

Page-count fallback (no units at all):
  - Pages grouped into chapters (10 pages each) and lessons (3 pages each)
"""

from __future__ import annotations

import base64
import logging
from collections import defaultdict
from uuid import UUID, uuid4

from learning_platform.models.book import (
    BookChapter,
    BookLesson,
    BookPage,
    CanonicalBook,
    CodeItem,
    ContentItem,
    EquationItem,
    HeadingItem,
    ImageItem,
    ListItem,
    TableItem,
    TextItem,
)
from learning_platform.models.document import CanonicalDocument, DocumentNode
from learning_platform.models.learning_unit import LearningUnit, UnitType

_LOG = logging.getLogger(__name__)

_SKIP_NODE_TYPES: frozenset[str] = frozenset(
    {"page_break", "page_header", "page_footer", "table_of_contents", "metadata_block"}
)

# Fallback grouping sizes when no structural units are detected
_FALLBACK_PAGES_PER_CHAPTER: int = 10
_FALLBACK_PAGES_PER_LESSON: int = 3


class BookAssembler:
    """Assembles a CanonicalBook from LearningUnits and a CanonicalDocument."""

    def assemble(
        self,
        units: list[LearningUnit],
        document: CanonicalDocument,
    ) -> CanonicalBook:
        """Build and return a CanonicalBook."""
        # Build a fast node_id → DocumentNode lookup
        node_map: dict[UUID, DocumentNode] = {n.id: n for n in document.nodes if hasattr(n, "id")}
        # Also walk children recursively if nodes is a tree (root only)
        if len(document.nodes) == 1 and document.nodes[0].children:
            node_map = {}
            self._collect_nodes(document.nodes[0], node_map)

        if not units:
            return self._fallback_from_pages(document, node_map)

        chapter_units = [u for u in units if u.unit_type in (UnitType.MODULE, UnitType.COURSE)]
        lesson_units = [u for u in units if u.unit_type in (UnitType.LESSON, UnitType.TOPIC)]

        if not chapter_units:
            # No chapter-level units — wrap everything in one synthetic chapter
            return self._single_chapter_book(document, units, lesson_units, node_map)

        return self._structured_book(document, chapter_units, lesson_units, node_map)

    # ------------------------------------------------------------------
    # Structured path — chapters detected
    # ------------------------------------------------------------------

    def _structured_book(
        self,
        document: CanonicalDocument,
        chapter_units: list[LearningUnit],
        lesson_units: list[LearningUnit],
        node_map: dict[UUID, DocumentNode],
    ) -> CanonicalBook:
        # Build parent_id → [lesson] map
        lessons_by_parent: dict[UUID | None, list[LearningUnit]] = defaultdict(list)
        for lu in lesson_units:
            lessons_by_parent[lu.parent_id].append(lu)

        chapters: list[BookChapter] = []
        for i, cu in enumerate(chapter_units):
            child_lessons = lessons_by_parent.get(cu.id, [])
            # Also pick up lessons with no known parent if this is the first chapter
            if i == 0:
                child_lessons = list(child_lessons) + lessons_by_parent.get(None, [])

            book_lessons = self._build_lessons(child_lessons, node_map)

            # If chapter has no lessons, derive pages directly from chapter nodes
            if not book_lessons:
                chapter_pages = self._pages_from_node_ids(cu.source_node_ids, node_map)
                if chapter_pages:
                    synthetic_lesson = BookLesson(
                        title=cu.title,
                        unit_id=cu.id,
                        order=0,
                        pages=chapter_pages,
                    )
                    book_lessons = [synthetic_lesson]

            chapters.append(
                BookChapter(
                    unit_id=cu.id,
                    title=cu.title,
                    order=i,
                    lessons=book_lessons,
                )
            )

        return CanonicalBook(
            document_id=document.metadata.source_path
            if hasattr(document.metadata, "source_path")
            else uuid4(),
            title=document.title or document.metadata.title or "",
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # Single-chapter fallback
    # ------------------------------------------------------------------

    def _single_chapter_book(
        self,
        document: CanonicalDocument,
        all_units: list[LearningUnit],
        lesson_units: list[LearningUnit],
        node_map: dict[UUID, DocumentNode],
    ) -> CanonicalBook:
        units_to_use = lesson_units if lesson_units else all_units
        book_lessons = self._build_lessons(units_to_use, node_map)

        chapter = BookChapter(
            title=document.title or document.metadata.title or "Document",
            order=0,
            lessons=book_lessons,
        )
        return CanonicalBook(
            document_id=uuid4(),
            title=document.title or document.metadata.title or "",
            chapters=[chapter],
        )

    # ------------------------------------------------------------------
    # Page-count fallback — no units at all
    # ------------------------------------------------------------------

    def _fallback_from_pages(
        self,
        document: CanonicalDocument,
        node_map: dict[UUID, DocumentNode],
    ) -> CanonicalBook:
        # Group all nodes by page number
        pages_map: dict[int, list[DocumentNode]] = defaultdict(list)
        for node in node_map.values():
            if node.page >= 0:
                pages_map[node.page].append(node)

        all_page_numbers = sorted(pages_map.keys())
        if not all_page_numbers:
            return CanonicalBook(document_id=uuid4(), title="", chapters=[])

        # Chunk pages into lessons, lessons into chapters
        lesson_chunks = [
            all_page_numbers[i : i + _FALLBACK_PAGES_PER_LESSON]
            for i in range(0, len(all_page_numbers), _FALLBACK_PAGES_PER_LESSON)
        ]
        chapter_chunks = [
            lesson_chunks[i : i + (_FALLBACK_PAGES_PER_CHAPTER // _FALLBACK_PAGES_PER_LESSON)]
            for i in range(
                0,
                len(lesson_chunks),
                _FALLBACK_PAGES_PER_CHAPTER // _FALLBACK_PAGES_PER_LESSON,
            )
        ]

        chapters: list[BookChapter] = []
        for ci, ch_chunk in enumerate(chapter_chunks):
            lessons: list[BookLesson] = []
            for li, lesson_pages in enumerate(ch_chunk):
                pages: list[BookPage] = []
                for pi, pn in enumerate(lesson_pages):
                    nodes = sorted(pages_map[pn], key=lambda n: n.seq)
                    items = self._nodes_to_items(nodes)
                    if items:
                        pages.append(BookPage(page_number=pn, order=pi, items=items))
                if pages:
                    lessons.append(
                        BookLesson(
                            title=f"Lesson {ci + 1}.{li + 1}",
                            order=li,
                            pages=pages,
                        )
                    )
            if lessons:
                chapters.append(
                    BookChapter(
                        title=f"Chapter {ci + 1}",
                        order=ci,
                        lessons=lessons,
                    )
                )

        return CanonicalBook(
            document_id=uuid4(),
            title=document.title or "",
            chapters=chapters,
        )

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_lessons(
        self,
        lesson_units: list[LearningUnit],
        node_map: dict[UUID, DocumentNode],
    ) -> list[BookLesson]:
        lessons: list[BookLesson] = []
        for i, lu in enumerate(lesson_units):
            pages = self._pages_from_node_ids(lu.source_node_ids, node_map)
            if pages:
                lessons.append(
                    BookLesson(
                        unit_id=lu.id,
                        title=lu.title,
                        order=i,
                        pages=pages,
                    )
                )
        return lessons

    def _pages_from_node_ids(
        self,
        node_ids: list[UUID],
        node_map: dict[UUID, DocumentNode],
    ) -> list[BookPage]:
        """Group a list of node IDs by page number and convert to BookPages."""
        page_buckets: dict[int, list[DocumentNode]] = defaultdict(list)
        for nid in node_ids:
            node = node_map.get(nid)
            if node is None:
                continue
            if node.page < 0:
                continue
            page_buckets[node.page].append(node)

        pages: list[BookPage] = []
        for pi, (page_number, nodes) in enumerate(
            sorted(page_buckets.items(), key=lambda kv: kv[0])
        ):
            sorted_nodes = sorted(nodes, key=lambda n: n.seq)
            items = self._nodes_to_items(sorted_nodes)
            if items:
                pages.append(BookPage(page_number=page_number, order=pi, items=items))
        return pages

    def _nodes_to_items(self, nodes: list[DocumentNode]) -> list[ContentItem]:
        """Convert DocumentNode list to typed ContentItem list."""
        items: list[ContentItem] = []
        order = 0
        for node in nodes:
            item = self._node_to_item(node, order)
            if item is not None:
                items.append(item)
                order += 1
        return items

    def _node_to_item(self, node: DocumentNode, order: int) -> ContentItem | None:
        """Convert a single DocumentNode to the appropriate ContentItem."""
        from learning_platform.models.document import (
            Callout,
            CodeBlock,
            Definition,
            Equation,
            Exercise,
            Figure,
            Heading,
            ListBlock,
            Note,
            Paragraph,
            Reference,
            TableBlock,
        )

        content = node.content
        node_type = getattr(content, "type", "")

        if node_type in _SKIP_NODE_TYPES:
            return None

        bbox = self._bbox(node)
        style = self._style(node)

        if isinstance(content, Heading):
            return HeadingItem(
                order=order,
                content=content.text.plain_text,
                level=node.level or content.level,
                bbox=bbox,
                style=style,
            )

        if isinstance(content, Paragraph):
            text = content.text.plain_text
            if not text.strip():
                return None
            return TextItem(order=order, content=text, bbox=bbox, style=style)

        if isinstance(content, (Note, Callout, Definition, Reference)):
            text = getattr(content, "text", None)
            plain = text.plain_text if text and hasattr(text, "plain_text") else str(content)
            if not plain.strip():
                return None
            return TextItem(order=order, content=plain, bbox=bbox, style=style)

        if isinstance(content, Exercise):
            text = content.question.plain_text if content.question else ""
            if not text.strip():
                return None
            return TextItem(order=order, content=text, bbox=bbox, style=style)

        if isinstance(content, ListBlock):
            item_texts = [it.text.plain_text for it in content.items]
            if not any(item_texts):
                return None
            return ListItem(
                order=order,
                ordered=content.ordered if hasattr(content, "ordered") else False,
                items=item_texts,
                bbox=bbox,
                style=style,
            )

        if isinstance(content, TableBlock):
            return TableItem(
                order=order,
                caption=content.caption if hasattr(content, "caption") else None,
                headers=content.headers if content.headers else [],
                rows=[
                    [cell if isinstance(cell, str) else str(cell) for cell in row]
                    for row in (content.rows if content.rows else [])
                ],
                bbox=bbox,
                style=style,
            )

        if isinstance(content, Equation):
            latex = content.latex or ""
            if not latex.strip():
                return None
            return EquationItem(
                order=order,
                latex=latex,
                label=content.label if hasattr(content, "label") else None,
                bbox=bbox,
            )

        if isinstance(content, CodeBlock):
            code = content.code or ""
            if not code.strip():
                return None
            return CodeItem(
                order=order,
                content=code,
                language=content.language if hasattr(content, "language") else None,
                bbox=bbox,
            )

        if isinstance(content, Figure):
            # Embed image as base64 if image_data is available
            data = ""
            if hasattr(content, "image_data") and content.image_data:
                if isinstance(content.image_data, bytes):
                    data = base64.b64encode(content.image_data).decode()
                else:
                    data = str(content.image_data)
            caption = ""
            if hasattr(content, "caption_text"):
                caption = content.caption_text
            elif hasattr(content, "alt_text"):
                caption = content.alt_text or ""
            return ImageItem(
                order=order,
                data=data,
                caption=caption or None,
                bbox=bbox,
            )

        return None

    @staticmethod
    def _bbox(node: DocumentNode) -> dict[str, float] | None:
        if node.bbox is None:
            return None
        b = node.bbox
        return {
            "x": b.x,
            "y": b.y,
            "width": b.width,
            "height": b.height,
            "page_width": b.page_width,
            "page_height": b.page_height,
        }

    @staticmethod
    def _style(node: DocumentNode) -> dict[str, object] | None:
        if node.style is None:
            return None
        s = node.style
        result: dict[str, object] = {}
        if hasattr(s, "font_name") and s.font_name:
            result["font_name"] = s.font_name
        if hasattr(s, "font_size") and s.font_size is not None:
            result["font_size"] = s.font_size
        if hasattr(s, "bold") and s.bold is not None:
            result["bold"] = s.bold
        if hasattr(s, "italic") and s.italic is not None:
            result["italic"] = s.italic
        if hasattr(s, "color") and s.color:
            result["color"] = s.color
        return result if result else None

    def _collect_nodes(self, node: DocumentNode, node_map: dict[UUID, DocumentNode]) -> None:
        """Recursively collect all nodes from the document tree."""
        node_map[node.id] = node
        for child in node.children:
            self._collect_nodes(child, node_map)
