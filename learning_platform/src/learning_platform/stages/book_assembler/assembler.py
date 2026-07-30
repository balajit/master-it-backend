"""Book Assembler — builds CanonicalBook via page-first segmentation.

Assembly flow:
  1. Group document nodes by page and convert each page to content items.
  2. Detect heading anchors from page content.
  3. Build lessons from pages:
     - heading-driven when lesson anchors exist
     - fallback chunking at 5 pages per lesson with adaptive +/-1
  4. Build chapters from lessons:
     - heading-driven when chapter anchors exist
     - fallback chunking at 5 lessons per chapter
  5. Map generated lessons/chapters back to Pipeline-1 LearningUnit IDs when possible.

The resulting shape is always:
  Chapter -> Lesson -> Page -> Item
"""

from __future__ import annotations

import base64
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
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
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentNode,
    Heading,
    HeadingLevel,
)
from learning_platform.models.learning_unit import LearningUnit, UnitType

_LOG = logging.getLogger(__name__)

_SKIP_NODE_TYPES: frozenset[str] = frozenset(
    {"page_break", "page_header", "page_footer", "table_of_contents", "metadata_block"}
)

_CHAPTER_KEYWORDS: frozenset[str] = frozenset({"chapter", "unit", "module", "part"})
_LESSON_KEYWORDS: frozenset[str] = frozenset({"lesson", "section", "topic", "lab"})

_LESSON_PAGES_TARGET: int = 5
_LESSON_PAGES_MIN: int = 4
_LESSON_PAGES_MAX: int = 6
_CHAPTER_LESSONS_TARGET: int = 5

_HEADING_PREFIX_RE: re.Pattern[str] = re.compile(
    r"^(?:chapter|unit|module|part|lesson|section|topic|lab)\b",
    re.IGNORECASE,
)


@dataclass
class _PageSlice:
    page_number: int
    nodes: list[DocumentNode] = field(default_factory=list)
    items: list[ContentItem] = field(default_factory=list)
    lesson_heading: str | None = None
    chapter_heading: str | None = None
    has_lesson_anchor: bool = False
    has_chapter_anchor: bool = False

    def node_ids(self) -> set[UUID]:
        return {node.id for node in self.nodes}


@dataclass
class _LessonSlice:
    title: str
    pages: list[_PageSlice] = field(default_factory=list)
    has_chapter_anchor: bool = False
    chapter_heading: str | None = None

    def node_ids(self) -> set[UUID]:
        result: set[UUID] = set()
        for page in self.pages:
            result.update(page.node_ids())
        return result


@dataclass
class _ChapterSlice:
    title: str
    lessons: list[_LessonSlice] = field(default_factory=list)

    def node_ids(self) -> set[UUID]:
        result: set[UUID] = set()
        for lesson in self.lessons:
            result.update(lesson.node_ids())
        return result


class BookAssembler:
    """Assembles a CanonicalBook from LearningUnits and a CanonicalDocument."""

    def assemble(
        self,
        units: list[LearningUnit],
        document: CanonicalDocument,
    ) -> CanonicalBook:
        """Build and return a CanonicalBook using page-first segmentation."""
        node_map = self._build_node_map(document)
        page_slices = self._build_page_slices(node_map)

        if not page_slices:
            return CanonicalBook(
                document_id=uuid4(),
                title=document.title or document.metadata.title or "",
                chapters=[],
            )

        lesson_slices = self._segment_lessons(page_slices)
        chapter_slices = self._segment_chapters(lesson_slices)

        chapter_units = [u for u in units if u.unit_type in (UnitType.MODULE, UnitType.COURSE)]
        lesson_units = [u for u in units if u.unit_type in (UnitType.LESSON, UnitType.TOPIC)]

        lesson_unit_matches = self._match_units_to_lesson_slices(lesson_slices, lesson_units)
        chapter_unit_matches = self._match_units_to_chapter_slices(chapter_slices, chapter_units)

        built_chapters: list[BookChapter] = []
        lesson_index = 0
        for chapter_order, chapter_slice in enumerate(chapter_slices):
            built_lessons: list[BookLesson] = []
            for lesson_order, lesson_slice in enumerate(chapter_slice.lessons):
                pages = [
                    BookPage(page_number=page.page_number, order=idx, items=page.items)
                    for idx, page in enumerate(lesson_slice.pages)
                ]
                if not pages:
                    continue

                matched_lesson_unit = lesson_unit_matches[lesson_index]
                built_lessons.append(
                    BookLesson(
                        unit_id=matched_lesson_unit.id
                        if matched_lesson_unit is not None
                        else None,
                        title=lesson_slice.title,
                        order=lesson_order,
                        pages=pages,
                    )
                )
                lesson_index += 1

            if not built_lessons:
                continue

            matched_chapter_unit = chapter_unit_matches[chapter_order]
            built_chapters.append(
                BookChapter(
                    unit_id=matched_chapter_unit.id if matched_chapter_unit is not None else None,
                    title=chapter_slice.title,
                    order=chapter_order,
                    lessons=built_lessons,
                )
            )

        return CanonicalBook(
            document_id=uuid4(),
            title=document.title or document.metadata.title or "",
            chapters=built_chapters,
        )

    # ------------------------------------------------------------------
    # Segmentation helpers
    # ------------------------------------------------------------------

    def _build_node_map(self, document: CanonicalDocument) -> dict[UUID, DocumentNode]:
        node_map: dict[UUID, DocumentNode] = {}
        for node in document.nodes:
            self._collect_nodes(node, node_map)
        return node_map

    def _build_page_slices(self, node_map: dict[UUID, DocumentNode]) -> list[_PageSlice]:
        page_buckets: dict[int, list[DocumentNode]] = defaultdict(list)
        for node in node_map.values():
            if node.page < 0:
                continue
            page_buckets[node.page].append(node)

        slices: list[_PageSlice] = []
        for page_number in sorted(page_buckets.keys()):
            nodes = sorted(page_buckets[page_number], key=lambda n: n.seq)
            items = self._nodes_to_items(nodes)
            if not items:
                continue
            chapter_heading, lesson_heading = self._extract_heading_signals(nodes)
            slices.append(
                _PageSlice(
                    page_number=page_number,
                    nodes=nodes,
                    items=items,
                    lesson_heading=lesson_heading,
                    chapter_heading=chapter_heading,
                    has_lesson_anchor=lesson_heading is not None,
                    has_chapter_anchor=chapter_heading is not None,
                )
            )

        return slices

    def _extract_heading_signals(
        self,
        nodes: list[DocumentNode],
    ) -> tuple[str | None, str | None]:
        chapter_heading: str | None = None
        lesson_heading: str | None = None

        for node in nodes:
            if not isinstance(node.content, Heading):
                continue
            text = node.content.text.plain_text.strip()
            if not text:
                continue

            heading_level = int(node.level or node.content.level)
            is_chapter, is_lesson = self._classify_heading(text, heading_level)
            if is_chapter and chapter_heading is None:
                chapter_heading = text
            if is_lesson and lesson_heading is None:
                lesson_heading = text

        return chapter_heading, lesson_heading

    @staticmethod
    def _classify_heading(text: str, heading_level: int) -> tuple[bool, bool]:
        stripped = text.strip()
        first_word = stripped.split()[0].lower().rstrip(".:") if stripped else ""

        if first_word in _CHAPTER_KEYWORDS:
            return True, False
        if first_word in _LESSON_KEYWORDS:
            return False, True

        if _HEADING_PREFIX_RE.match(stripped):
            prefix = stripped.split()[0].lower().rstrip(".:")
            if prefix in _CHAPTER_KEYWORDS:
                return True, False
            if prefix in _LESSON_KEYWORDS:
                return False, True

        if heading_level <= int(HeadingLevel.CHAPTER):
            return True, False
        if heading_level <= int(HeadingLevel.SECTION):
            return False, True
        return False, False

    def _segment_lessons(self, pages: list[_PageSlice]) -> list[_LessonSlice]:
        if not pages:
            return []

        if any(page.has_lesson_anchor for page in pages):
            return self._segment_lessons_by_anchors(pages)

        return self._segment_lessons_by_fallback(pages)

    def _segment_lessons_by_anchors(self, pages: list[_PageSlice]) -> list[_LessonSlice]:
        lessons: list[_LessonSlice] = []
        current_pages: list[_PageSlice] = []

        for idx, page in enumerate(pages):
            if idx == 0:
                current_pages = [page]
                continue

            if page.has_lesson_anchor and current_pages:
                lessons.append(self._lesson_slice_from_pages(current_pages, len(lessons)))
                current_pages = [page]
                continue

            current_pages.append(page)

        if current_pages:
            lessons.append(self._lesson_slice_from_pages(current_pages, len(lessons)))

        return lessons

    def _segment_lessons_by_fallback(self, pages: list[_PageSlice]) -> list[_LessonSlice]:
        chunk_sizes = self._adaptive_lesson_chunk_sizes(len(pages))
        lessons: list[_LessonSlice] = []
        index = 0

        for chunk_size in chunk_sizes:
            chunk = pages[index : index + chunk_size]
            if chunk:
                lessons.append(self._lesson_slice_from_pages(chunk, len(lessons)))
            index += chunk_size

        return lessons

    def _lesson_slice_from_pages(self, pages: list[_PageSlice], lesson_index: int) -> _LessonSlice:
        title = self._lesson_title_from_pages(pages, lesson_index)
        chapter_heading = next((p.chapter_heading for p in pages if p.chapter_heading), None)
        has_chapter_anchor = any(p.has_chapter_anchor for p in pages)
        return _LessonSlice(
            title=title,
            pages=pages,
            has_chapter_anchor=has_chapter_anchor,
            chapter_heading=chapter_heading,
        )

    @staticmethod
    def _lesson_title_from_pages(pages: list[_PageSlice], lesson_index: int) -> str:
        for page in pages:
            if page.lesson_heading:
                return page.lesson_heading
        for page in pages:
            if page.chapter_heading:
                return page.chapter_heading
        return f"Lesson {lesson_index + 1}"

    @staticmethod
    def _adaptive_lesson_chunk_sizes(total_pages: int) -> list[int]:
        if total_pages <= 0:
            return []
        if total_pages <= _LESSON_PAGES_MAX:
            return [total_pages]

        valid_chunk_counts = [
            chunks
            for chunks in range(1, total_pages + 1)
            if _LESSON_PAGES_MIN * chunks <= total_pages <= _LESSON_PAGES_MAX * chunks
        ]

        if valid_chunk_counts:
            chunk_count = min(
                valid_chunk_counts,
                key=lambda chunks: abs((total_pages / chunks) - _LESSON_PAGES_TARGET),
            )
        else:
            chunk_count = max(1, round(total_pages / _LESSON_PAGES_TARGET))

        base = total_pages // chunk_count
        remainder = total_pages % chunk_count

        sizes = [base for _ in range(chunk_count)]
        for idx in range(remainder):
            sizes[idx] += 1

        return [size for size in sizes if size > 0]

    def _segment_chapters(self, lessons: list[_LessonSlice]) -> list[_ChapterSlice]:
        if not lessons:
            return []

        if any(lesson.has_chapter_anchor for lesson in lessons):
            return self._segment_chapters_by_anchors(lessons)

        return self._segment_chapters_by_fallback(lessons)

    def _segment_chapters_by_anchors(self, lessons: list[_LessonSlice]) -> list[_ChapterSlice]:
        chapters: list[_ChapterSlice] = []
        current_lessons: list[_LessonSlice] = []

        for idx, lesson in enumerate(lessons):
            if idx == 0:
                current_lessons = [lesson]
                continue

            if lesson.has_chapter_anchor and current_lessons:
                chapters.append(self._chapter_slice_from_lessons(current_lessons, len(chapters)))
                current_lessons = [lesson]
                continue

            current_lessons.append(lesson)

        if current_lessons:
            chapters.append(self._chapter_slice_from_lessons(current_lessons, len(chapters)))

        return chapters

    def _segment_chapters_by_fallback(self, lessons: list[_LessonSlice]) -> list[_ChapterSlice]:
        chapters: list[_ChapterSlice] = []
        for i in range(0, len(lessons), _CHAPTER_LESSONS_TARGET):
            chunk = lessons[i : i + _CHAPTER_LESSONS_TARGET]
            if chunk:
                chapters.append(self._chapter_slice_from_lessons(chunk, len(chapters)))
        return chapters

    @staticmethod
    def _chapter_slice_from_lessons(
        lessons: list[_LessonSlice],
        chapter_index: int,
    ) -> _ChapterSlice:
        title = next(
            (lesson.chapter_heading for lesson in lessons if lesson.chapter_heading), None
        )
        if not title:
            title = f"Chapter {chapter_index + 1}"
        return _ChapterSlice(title=title, lessons=lessons)

    # ------------------------------------------------------------------
    # Unit matching helpers
    # ------------------------------------------------------------------

    def _match_units_to_lesson_slices(
        self,
        lessons: list[_LessonSlice],
        lesson_units: list[LearningUnit],
    ) -> list[LearningUnit | None]:
        segment_node_ids = [lesson.node_ids() for lesson in lessons]
        return self._match_units_to_segments(segment_node_ids, lesson_units)

    def _match_units_to_chapter_slices(
        self,
        chapters: list[_ChapterSlice],
        chapter_units: list[LearningUnit],
    ) -> list[LearningUnit | None]:
        segment_node_ids = [chapter.node_ids() for chapter in chapters]
        return self._match_units_to_segments(segment_node_ids, chapter_units)

    @staticmethod
    def _match_units_to_segments(
        segment_node_ids: list[set[UUID]],
        units: list[LearningUnit],
    ) -> list[LearningUnit | None]:
        if not segment_node_ids:
            return []
        if not units:
            return [None for _ in segment_node_ids]

        unit_node_ids = [set(unit.source_node_ids) for unit in units]
        assignments: list[LearningUnit | None] = [None for _ in segment_node_ids]
        remaining_units: set[int] = set(range(len(units)))

        # Pass 1: assign by strongest positive overlap.
        while True:
            best_segment_idx: int | None = None
            best_unit_idx: int | None = None
            best_score = 0

            for segment_idx, segment_ids in enumerate(segment_node_ids):
                if assignments[segment_idx] is not None:
                    continue
                for unit_idx in remaining_units:
                    score = len(segment_ids.intersection(unit_node_ids[unit_idx]))
                    if score > best_score:
                        best_score = score
                        best_segment_idx = segment_idx
                        best_unit_idx = unit_idx

            if best_segment_idx is None or best_unit_idx is None or best_score <= 0:
                break

            assignments[best_segment_idx] = units[best_unit_idx]
            remaining_units.remove(best_unit_idx)

        # Pass 2: order-based fallback for still-unassigned segments.
        unassigned_segments = [
            idx for idx, assignment in enumerate(assignments) if assignment is None
        ]
        for segment_idx, unit_idx in zip(
            unassigned_segments,
            sorted(remaining_units),
            strict=False,
        ):
            assignments[segment_idx] = units[unit_idx]

        return assignments

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
