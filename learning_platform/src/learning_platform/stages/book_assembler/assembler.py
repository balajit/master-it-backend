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
    FormAreaItem,
    HeadingItem,
    ImageItem,
    ListItem,
    QuestionBlank,
    QuestionItem,
    QuestionOption,
    QuestionStatement,
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
_FILL_BLANK_RE: re.Pattern[str] = re.compile(r"\((\d+)\)\s*(?:_{2,}|\.+|$)")
_NUMBERED_ITEM_RE: re.Pattern[str] = re.compile(r"^\s*(\d+)[.)]\s+")
_PAGE_TOP_MARGIN_MAX: float = 45.0
_PAGE_BOTTOM_MARGIN_MAX: float = 55.0
_QUESTION_CONTINUATION_MAX_GAP: float = 24.0

_PAGE_CHROME_FRAGMENT_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bstudy\s+guide\s+for\s+content\s+mastery\b", re.IGNORECASE),
    re.compile(
        r"\bchemistry:\s*matter\s+and\s+change\s*[•·]?\s*chapter\s*\d+\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bname\s+date\s+class(?:\s+\d+)?\b", re.IGNORECASE),
    re.compile(
        r"\bcopyright\s+©?\s*glencoe/mcgraw-hill[^\n]*",
        re.IGNORECASE,
    ),
)


def _normalized_heading_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


def _normalized_inline_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().lower()


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
                    BookPage(
                        page_number=page.page_number,
                        order=idx,
                        items=page.items,
                        metadata=self._page_metadata(document, page),
                    )
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
            deduped_nodes = self._dedupe_page_headings(page_buckets[page_number])
            nodes = sorted(deduped_nodes, key=lambda n: n.seq)
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

    def _dedupe_page_headings(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        seen: set[tuple[int, str]] = set()
        result: list[DocumentNode] = []

        for node in sorted(nodes, key=lambda n: n.seq):
            if not isinstance(node.content, Heading):
                result.append(node)
                continue

            heading_text = _normalized_heading_text(node.content.text.plain_text)
            if not heading_text:
                result.append(node)
                continue

            key = (node.page, heading_text)
            if key in seen:
                continue
            seen.add(key)
            result.append(node)

        return result

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
        node_by_id: dict[UUID, DocumentNode] = {node.id: node for node in nodes}
        order = 0
        for node in nodes:
            parent_node = node_by_id.get(node.parent_id) if node.parent_id is not None else None
            if (
                getattr(node.content, "type", "") == "text_item"
                and parent_node is not None
                and getattr(parent_node.content, "type", "") == "form_area"
            ):
                continue
            item = self._node_to_item(node, order)
            if item is not None:
                items.append(item)
                order += 1
        return self._normalize_page_items(items)

    def _normalize_page_items(self, items: list[ContentItem]) -> list[ContentItem]:
        cleaned = self._strip_page_chrome(items)
        deduped = self._dedupe_heading_text_echoes(cleaned)
        promoted = self._promote_list_true_false_items(deduped)
        return self._reindex_items(promoted)

    def _strip_page_chrome(self, items: list[ContentItem]) -> list[ContentItem]:
        result: list[ContentItem] = []
        for item in items:
            if item.type not in {"text", "heading"}:
                result.append(item)
                continue

            raw_text = str(getattr(item, "content", ""))
            raw_text_stripped = raw_text.strip()
            cleaned_text = self._strip_page_chrome_fragments(raw_text)

            if self._is_margin_chrome_item(item, raw_text):
                continue
            if raw_text_stripped and cleaned_text == "":
                continue

            if cleaned_text != raw_text:
                clone = item.model_copy(deep=True)
                clone.content = cleaned_text
                metadata = dict(getattr(clone, "metadata", {}) or {})
                metadata["chrome_sanitized"] = True
                clone.metadata = metadata
                result.append(clone)
                continue

            result.append(item)
        return result

    def _dedupe_heading_text_echoes(self, items: list[ContentItem]) -> list[ContentItem]:
        if not items:
            return []

        result: list[ContentItem] = []
        for item in items:
            if (
                item.type == "text"
                and result
                and result[-1].type == "heading"
                and _normalized_inline_text(item.content)
                == _normalized_inline_text(result[-1].content)
            ):
                continue
            result.append(item)
        return result

    def _promote_list_true_false_items(self, items: list[ContentItem]) -> list[ContentItem]:
        if not items:
            return []

        result: list[ContentItem] = []
        for index, item in enumerate(items):
            if item.type != "list" or len(item.items) != 1:
                result.append(item)
                continue

            candidate_text = item.items[0].strip()
            numbered = _NUMBERED_ITEM_RE.match(candidate_text)
            if numbered is None:
                result.append(item)
                continue

            statement_number = int(numbered.group(1))
            if not self._adjacent_true_false_context(items, index, statement_number):
                result.append(item)
                continue

            statement_text = candidate_text[numbered.end() :].strip()
            if not statement_text:
                result.append(item)
                continue

            question_metadata: dict[str, object] = {
                **(item.metadata or {}),
                "semantic_type": "question",
                "question_type": "true_false",
                "question_signal": "list_true_false",
                "numbered_item": statement_number,
                "statement_count": 1,
            }
            result.append(
                QuestionItem(
                    order=item.order,
                    question_type="true_false",
                    content=candidate_text,
                    statements=[QuestionStatement(number=statement_number, text=statement_text)],
                    bbox=item.bbox,
                    style=item.style,
                    metadata=question_metadata,
                )
            )

        return result

    def _join_question_continuations(self, items: list[ContentItem]) -> list[ContentItem]:
        if not items:
            return []

        result: list[ContentItem] = []
        for item in items:
            if (
                item.type == "text"
                and result
                and result[-1].type == "question"
                and self._should_append_to_previous_question(result[-1], item)
            ):
                previous = result[-1].model_copy(deep=True)
                append_text = item.content.strip()
                previous.content = f"{previous.content.rstrip()} {append_text}".strip()
                if previous.statements:
                    last_statement = previous.statements[-1]
                    last_statement.text = f"{last_statement.text.rstrip()} {append_text}".strip()
                metadata = dict(previous.metadata or {})
                metadata["statement_continued"] = True
                previous.metadata = metadata
                result[-1] = previous
                continue
            result.append(item)
        return result

    @staticmethod
    def _reindex_items(items: list[ContentItem]) -> list[ContentItem]:
        reindexed: list[ContentItem] = []
        for order, item in enumerate(items):
            if item.order == order:
                reindexed.append(item)
                continue
            clone = item.model_copy(deep=True)
            clone.order = order
            reindexed.append(clone)
        return reindexed

    @staticmethod
    def _strip_page_chrome_fragments(raw_text: str) -> str:
        cleaned = raw_text
        for pattern in _PAGE_CHROME_FRAGMENT_PATTERNS:
            cleaned = pattern.sub(" ", cleaned)
        cleaned = re.sub(r"\s+", " ", cleaned).strip(" -•|\t\n")
        if cleaned.lower() == "class":
            return ""
        if re.fullmatch(r"\d+", cleaned):
            return ""
        return cleaned

    def _is_margin_chrome_item(self, item: ContentItem, text: str) -> bool:
        bbox = item.bbox or {}
        y_raw = bbox.get("y")
        page_height_raw = bbox.get("page_height")
        if not isinstance(y_raw, (int, float)):
            return False
        y_value = float(y_raw)
        page_height = float(page_height_raw) if isinstance(page_height_raw, (int, float)) else 0.0
        in_top_margin = y_value <= _PAGE_TOP_MARGIN_MAX
        in_bottom_margin = page_height > 0.0 and y_value >= (page_height - _PAGE_BOTTOM_MARGIN_MAX)
        if not (in_top_margin or in_bottom_margin):
            return False
        return self._looks_like_page_chrome_text(text)

    @staticmethod
    def _looks_like_page_chrome_text(text: str) -> bool:
        normalized = _normalized_inline_text(text)
        if not normalized:
            return False
        if normalized in {"class", "name", "date", "name date class"}:
            return True
        return (
            "study guide for content mastery" in normalized
            or "name date class" in normalized
            or ("copyright" in normalized and "mcgraw-hill" in normalized)
            or ("chemistry: matter and change" in normalized and "chapter" in normalized)
        )

    @staticmethod
    def _adjacent_true_false_context(
        items: list[ContentItem],
        index: int,
        statement_number: int,
    ) -> bool:
        neighbor_indexes = (index - 1, index + 1)
        for neighbor_index in neighbor_indexes:
            if neighbor_index < 0 or neighbor_index >= len(items):
                continue
            neighbor = items[neighbor_index]
            if neighbor.type != "question":
                continue
            if neighbor.question_type != "true_false":
                continue
            neighbor_number = BookAssembler._extract_numbered_item(neighbor)
            if neighbor_number is None:
                continue
            if abs(neighbor_number - statement_number) <= 2:
                return True
        return False

    @staticmethod
    def _extract_numbered_item(question: QuestionItem) -> int | None:
        metadata_value = question.metadata.get("numbered_item") if question.metadata else None
        if isinstance(metadata_value, int):
            return metadata_value
        if isinstance(metadata_value, str) and metadata_value.isdigit():
            return int(metadata_value)
        numbered = _NUMBERED_ITEM_RE.match(question.content)
        if numbered is None:
            return None
        return int(numbered.group(1))

    def _should_append_to_previous_question(
        self,
        question: QuestionItem,
        continuation: TextItem,
    ) -> bool:
        if question.question_type != "true_false":
            return False
        tail = continuation.content.strip()
        if not tail:
            return False
        if re.match(r"^[A-Z]", tail):
            return False

        question_text = question.content.strip()
        if not question_text:
            return False
        if question_text.endswith((".", "?", "!", ":", ";")):
            return False

        question_bbox = question.bbox or {}
        continuation_bbox = continuation.bbox or {}
        q_y = question_bbox.get("y")
        q_h = question_bbox.get("height")
        t_y = continuation_bbox.get("y")
        if not isinstance(q_y, (int, float)):
            return False
        if not isinstance(q_h, (int, float)):
            return False
        if not isinstance(t_y, (int, float)):
            return False
        q_bottom = float(q_y) + float(q_h)
        vertical_gap = float(t_y) - q_bottom
        return 0.0 <= vertical_gap <= _QUESTION_CONTINUATION_MAX_GAP

    def _node_to_item(self, node: DocumentNode, order: int) -> ContentItem | None:
        """Convert a single DocumentNode to the appropriate ContentItem."""
        from learning_platform.models.document import (
            Callout,
            CodeBlock,
            Definition,
            Equation,
            Exercise,
            Figure,
            FormAreaBlock,
            Heading,
            ListBlock,
            Note,
            Paragraph,
            Question,
            Reference,
            TableBlock,
        )
        from learning_platform.models.document import (
            TextItem as CanonicalTextItem,
        )

        content = node.content
        node_type = getattr(content, "type", "")

        if node_type in _SKIP_NODE_TYPES:
            return None

        bbox = self._bbox(node)
        style = self._style(node)

        if isinstance(content, Heading):
            heading_metadata: dict[str, object] = dict(content.metadata or {})
            if content.number:
                heading_metadata.setdefault("number", content.number)
            heading_metadata.setdefault("heading_level", int(content.level))
            heading_metadata.setdefault("node_level", int(node.level or content.level))
            heading_text_runs = self._styled_text_metadata(content.text)
            if heading_text_runs is not None:
                heading_metadata.setdefault("text_runs", heading_text_runs)
            return HeadingItem(
                order=order,
                content=content.text.plain_text,
                level=node.level or content.level,
                bbox=bbox,
                style=style,
                metadata=heading_metadata,
            )

        if isinstance(content, Paragraph):
            text = content.text.plain_text
            if not text.strip():
                return None
            paragraph_metadata: dict[str, object] = {
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            if node.source.offset > 0:
                paragraph_metadata.setdefault("source_offset", node.source.offset)
            if node.source.length > 0:
                paragraph_metadata.setdefault("source_length", node.source.length)
            paragraph_text_runs = self._styled_text_metadata(content.text)
            if paragraph_text_runs is not None:
                paragraph_metadata.setdefault("text_runs", paragraph_text_runs)
            paragraph_metadata.update(self._text_ui_hints(text, node.metadata.get("label")))
            return TextItem(
                order=order,
                content=text,
                bbox=bbox,
                style=style,
                metadata=paragraph_metadata,
            )

        if isinstance(content, CanonicalTextItem):
            text = content.text.plain_text
            if not text.strip():
                return None
            text_item_metadata: dict[str, object] = {
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            if node.source.offset > 0:
                text_item_metadata.setdefault("source_offset", node.source.offset)
            if node.source.length > 0:
                text_item_metadata.setdefault("source_length", node.source.length)
            text_runs = self._styled_text_metadata(content.text)
            if text_runs is not None:
                text_item_metadata.setdefault("text_runs", text_runs)
            text_item_metadata.update(self._text_ui_hints(text, node.metadata.get("label")))
            return TextItem(
                order=order,
                content=text,
                bbox=bbox,
                style=style,
                metadata=text_item_metadata,
            )

        if isinstance(content, FormAreaBlock):
            form_items: list[str] = []
            for child in node.children:
                child_content = child.content
                if isinstance(child_content, CanonicalTextItem):
                    child_text = child_content.text.plain_text.strip()
                    if child_text:
                        form_items.append(child_text)

            form_metadata: dict[str, object] = {
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            if content.display_hint is not None:
                form_metadata["display_hint"] = content.display_hint

            return FormAreaItem(
                order=order,
                items=form_items,
                bbox=bbox,
                style=style,
                metadata=form_metadata,
            )

        if isinstance(content, (Note, Callout, Definition, Reference)):
            text = getattr(content, "text", None)
            plain = text.plain_text if text and hasattr(text, "plain_text") else str(content)
            if not plain.strip():
                return None
            semantic_metadata: dict[str, object] = {
                "semantic_type": getattr(content, "type", "text"),
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            semantic_metadata.update(self._text_ui_hints(plain, node.metadata.get("label")))
            return TextItem(
                order=order,
                content=plain,
                bbox=bbox,
                style=style,
                metadata=semantic_metadata,
            )

        if isinstance(content, Exercise):
            text = content.question.plain_text if content.question else ""
            if not text.strip():
                return None
            exercise_metadata: dict[str, object] = {
                "semantic_type": "exercise",
                "exercise_type": content.exercise_type.value,
                "option_count": len(content.options),
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            exercise_metadata.update(self._text_ui_hints(text, node.metadata.get("label")))
            return TextItem(
                order=order,
                content=text,
                bbox=bbox,
                style=style,
                metadata=exercise_metadata,
            )

        if isinstance(content, Question):
            question_text = content.text.plain_text if content.text else ""
            if not question_text.strip() and content.statements:
                question_text = " ".join(
                    statement.text.plain_text for statement in content.statements
                ).strip()
            if not question_text.strip():
                return None

            if content.question_type.value == "true_false" and len(content.statements) > 1:
                numbered = [
                    str(statement.number)
                    for statement in content.statements
                    if statement.number is not None
                ]
                if numbered:
                    question_text = (
                        f"Statements {numbered[0]}-{numbered[-1]}"
                        if len(numbered) > 1
                        else question_text
                    )

            question_metadata: dict[str, object] = {
                "semantic_type": "question",
                "question_type": content.question_type.value,
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            question_metadata.setdefault("statement_count", len(content.statements))
            question_metadata.update(
                self._text_ui_hints(question_text, node.metadata.get("label"))
            )

            options: list[QuestionOption] = []
            for option in content.options:
                options.append(
                    QuestionOption(
                        label=option.label,
                        text=option.text.plain_text,
                        is_correct=option.is_correct,
                        explanation=option.explanation,
                    )
                )

            blanks: list[QuestionBlank] = []
            for blank in content.blanks:
                blanks.append(
                    QuestionBlank(
                        blank_id=blank.blank_id,
                        placeholder=blank.placeholder,
                        answer=blank.answer,
                        metadata=dict(blank.metadata or {}),
                    )
                )

            statements: list[QuestionStatement] = []
            for statement in content.statements:
                statements.append(
                    QuestionStatement(
                        number=statement.number,
                        text=statement.text.plain_text,
                        expected_answer=statement.expected_answer,
                        metadata=dict(statement.metadata or {}),
                    )
                )

            return QuestionItem(
                order=order,
                question_type=content.question_type.value,
                content=question_text,
                options=options,
                blanks=blanks,
                statements=statements,
                solution=content.solution,
                explanation=content.explanation,
                points=content.points,
                bbox=bbox,
                style=style,
                metadata=question_metadata,
            )

        if isinstance(content, ListBlock):
            item_texts = [it.text.plain_text for it in content.items]
            if not any(item_texts):
                return None
            list_metadata: dict[str, object] = {
                "list_style": content.style.value,
                "item_count": len(content.items),
                "checked_count": sum(1 for it in content.items if it.checked is True),
                "unchecked_count": sum(1 for it in content.items if it.checked is False),
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            item_runs: list[list[dict[str, object]]] = []
            has_runs = False
            for list_item in content.items:
                run_meta = self._styled_text_metadata(list_item.text)
                if run_meta is None:
                    item_runs.append([])
                    continue
                has_runs = True
                item_runs.append(run_meta)
            if has_runs:
                list_metadata["item_text_runs"] = item_runs
            return ListItem(
                order=order,
                ordered=content.ordered if hasattr(content, "ordered") else False,
                items=item_texts,
                bbox=bbox,
                style=style,
                metadata=list_metadata,
            )

        if isinstance(content, TableBlock):
            table_metadata: dict[str, object] = {
                "row_count": content.row_count,
                "column_count": content.column_count,
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            serialized_rows: list[list[str]] = []
            for row in content.rows if content.rows else []:
                row_cells: list[str] = []
                for cell in row.cells:
                    cell_text = "".join(run.text for run in cell.content).strip()
                    row_cells.append(cell_text)
                serialized_rows.append(row_cells)

            return TableItem(
                order=order,
                caption=content.caption if hasattr(content, "caption") else None,
                headers=content.headers if content.headers else [],
                rows=serialized_rows,
                bbox=bbox,
                style=style,
                metadata=table_metadata,
            )

        if isinstance(content, Equation):
            latex = content.latex or ""
            if not latex.strip():
                return None
            equation_metadata: dict[str, object] = {
                "is_block": bool(content.is_block),
                "has_mathml": bool(content.mathml.strip()),
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            return EquationItem(
                order=order,
                latex=latex,
                label=content.label if hasattr(content, "label") else None,
                bbox=bbox,
                metadata=equation_metadata,
            )

        if isinstance(content, CodeBlock):
            code = content.code or ""
            if not code.strip():
                return None
            code_metadata: dict[str, object] = {
                "filename": content.filename,
                "line_start": content.line_start,
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            return CodeItem(
                order=order,
                content=code,
                language=content.language if hasattr(content, "language") else None,
                bbox=bbox,
                metadata=code_metadata,
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
            figure_metadata: dict[str, object] = {
                "image_uri": content.image_uri,
                "alt_text": content.alt_text,
                "caption_text": content.caption_text,
                "mimetype": content.mimetype,
                "format": content.format,
                "storage_key": content.storage_key,
                "size_bytes": content.size_bytes,
                "width": content.width,
                "height": content.height,
                **(content.metadata or {}),
                **(node.metadata or {}),
            }
            return ImageItem(
                order=order,
                data=data,
                caption=caption or None,
                bbox=bbox,
                metadata=figure_metadata,
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
        result: dict[str, object] = {
            "alignment": s.alignment.value,
            "indent_level": s.indent_level,
            "line_spacing": s.line_spacing,
            "space_before": s.space_before,
            "space_after": s.space_after,
            "background_color": s.background_color,
            "border_color": s.border_color,
            "border_width": s.border_width,
            "padding": s.padding,
        }

        font_info = BookAssembler._font_to_dict(s.font)
        if font_info:
            result["font"] = font_info

        if s.metadata:
            result["metadata"] = dict(s.metadata)
        return result if result else None

    @staticmethod
    def _font_to_dict(font: object) -> dict[str, object]:
        if font is None:
            return {}
        result: dict[str, object] = {}
        name = getattr(font, "name", "")
        if isinstance(name, str) and name:
            result["name"] = name

        size = getattr(font, "size", 0.0)
        if isinstance(size, (int, float)) and size:
            result["size"] = float(size)

        for attr in ("is_bold", "is_italic", "is_underline", "is_strikethrough"):
            value = getattr(font, attr, None)
            if value is not None:
                result[attr] = bool(value)

        color = getattr(font, "color", "")
        if isinstance(color, str) and color:
            result["color"] = color

        background_color = getattr(font, "background_color", "")
        if isinstance(background_color, str) and background_color:
            result["background_color"] = background_color
        return result

    @staticmethod
    def _styled_text_metadata(styled_text: object) -> list[dict[str, object]] | None:
        runs = getattr(styled_text, "runs", None)
        if not isinstance(runs, list) or not runs:
            return None

        serialized_runs: list[dict[str, object]] = []
        has_style = False
        for run in runs:
            run_payload: dict[str, object] = {"text": getattr(run, "text", "")}
            link_target = getattr(run, "link_target", "")
            if isinstance(link_target, str) and link_target:
                run_payload["link_target"] = link_target

            style_payload: dict[str, object] = {}
            run_style = getattr(run, "style", None)
            if run_style is not None:
                font_payload = BookAssembler._font_to_dict(getattr(run_style, "font", None))
                if font_payload:
                    style_payload["font"] = font_payload
                baseline_shift = getattr(run_style, "baseline_shift", 0.0)
                if baseline_shift:
                    style_payload["baseline_shift"] = baseline_shift
                language = getattr(run_style, "language", "")
                if isinstance(language, str) and language:
                    style_payload["language"] = language

            run_metadata = getattr(run, "metadata", None)
            if isinstance(run_metadata, dict) and run_metadata:
                style_payload["metadata"] = dict(run_metadata)

            if style_payload:
                has_style = True
                run_payload["style"] = style_payload

            serialized_runs.append(run_payload)

        if not has_style and len(serialized_runs) == 1:
            return None
        return serialized_runs

    @staticmethod
    def _page_metadata(document: CanonicalDocument, page: _PageSlice) -> dict[str, object]:
        labels: list[str] = []
        parent_refs: list[str] = []
        label_counts: dict[str, int] = {}
        for node in page.nodes:
            label = node.metadata.get("label")
            if isinstance(label, str) and label:
                labels.append(label)
                label_counts[label] = label_counts.get(label, 0) + 1
            parent_ref = node.metadata.get("docling_parent_ref")
            if isinstance(parent_ref, str) and parent_ref:
                parent_refs.append(parent_ref)

        metadata: dict[str, object] = {
            "source_node_ids": [str(node.id) for node in page.nodes],
            "docling_labels": sorted(set(labels)),
            "docling_label_counts": label_counts,
            "docling_parent_refs": sorted(set(parent_refs)),
        }

        parse_meta = document.metadata.custom.get("docling_parse")
        if isinstance(parse_meta, dict):
            metadata["ocr_enabled"] = bool(parse_meta.get("ocr_enabled", False))
            metadata["pdf_document_class"] = str(parse_meta.get("pdf_document_class", "unknown"))
            if parse_meta.get("hybrid_enabled") is True:
                metadata["hybrid_enabled"] = True
                metadata["layout_pages"] = int(parse_meta.get("layout_pages", 0) or 0)
                metadata["semantic_candidates"] = int(
                    parse_meta.get("semantic_candidates", 0) or 0
                )

            selected_reasons = parse_meta.get("selected_reasons")
            if isinstance(selected_reasons, dict):
                reasons = selected_reasons.get(str(page.page_number))
                if isinstance(reasons, list) and reasons:
                    metadata["second_pass_reasons"] = [str(reason) for reason in reasons]

        return metadata

    @staticmethod
    def _text_ui_hints(raw_text: str, label: object) -> dict[str, object]:
        hints: dict[str, object] = {}
        text = raw_text.strip()
        if not text:
            return hints

        numbered = _NUMBERED_ITEM_RE.match(text)
        if numbered is not None:
            hints["numbered_item"] = int(numbered.group(1))

        fill_blank_ids = [int(match.group(1)) for match in _FILL_BLANK_RE.finditer(text)]
        if fill_blank_ids:
            hints["has_fill_in_blanks"] = True
            hints["fill_in_blank_ids"] = fill_blank_ids

        if len(fill_blank_ids) >= 2:
            positions: list[int] = []
            for match in _FILL_BLANK_RE.finditer(text):
                positions.append(int(match.start()))
            hints["blank_span_positions"] = positions

        if isinstance(label, str) and label.startswith("checkbox_"):
            hints["checkbox_state"] = label.removeprefix("checkbox_")

        return hints

    def _collect_nodes(self, node: DocumentNode, node_map: dict[UUID, DocumentNode]) -> None:
        """Recursively collect all nodes from the document tree."""
        node_map[node.id] = node
        for child in node.children:
            self._collect_nodes(child, node_map)
