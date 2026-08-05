"""Canonical Document Model — the normalized representation of any parsed document.

All stages read from and write to this model. It is the single source of truth
for document content as it flows through the pipeline.

Design Principles
-----------------
- **Tree structure**: Every document is a tree. The root is a
  ``CanonicalDocument``; all content lives inside ``DocumentNode`` instances
  linked by parent/child references.
- **Discriminated union content**: Each ``DocumentNode`` holds exactly one
  ``ContentBlock`` variant, discriminated by the ``type`` field. This gives
  exhaustive type safety without inheritance.
- **Flat indexing**: ``CanonicalDocument.nodes`` stores a flat list of every
  node. ``CanonicalDocument.node_map`` provides ``UUID → DocumentNode`` lookup.
- **Source fidelity**: Every node preserves its position in the original file
  (``SourceLocation``), its spatial position on the page (``BoundingBox``),
  and its visual styling (``StylingInfo``).
- **Page-level tracking**: Nodes declare which page they belong to. Page
  breaks, headers, and footers are explicit node types.
"""

from __future__ import annotations

import base64
from enum import IntEnum, StrEnum
from typing import Annotated, Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, BeforeValidator, Field, PlainSerializer


def _image_bytes_validator(v: Any) -> bytes | None:
    """Accept raw bytes or a base64-encoded string; always store as raw bytes."""
    if v is None:
        return None
    if isinstance(v, (bytes, bytearray)):
        return bytes(v)
    if isinstance(v, str):
        return base64.b64decode(v)
    return bytes(v)


def _image_bytes_json_serializer(v: bytes | None) -> str | None:
    """Serialize raw bytes as a base64 string in JSON mode."""
    if v is None:
        return None
    return base64.b64encode(v).decode("ascii")


# Raw bytes in Python; base64 string when serialized to JSON.
ImageBytes = Annotated[
    bytes,
    BeforeValidator(_image_bytes_validator),
    PlainSerializer(_image_bytes_json_serializer, return_type=str, when_used="json"),
]

# ──────────────────────────────────────────────────────────────────────────────
# Enums
# ──────────────────────────────────────────────────────────────────────────────


class NodeType(StrEnum):
    """Discriminator values for ``DocumentNode.content``.

    Each value corresponds to exactly one ``ContentBlock`` subclass. The
    ``type`` field on ``DocumentNode`` must match the content it carries.
    """

    PARAGRAPH = "paragraph"
    HEADING = "heading"
    LIST = "list"
    TABLE = "table"
    FIGURE = "figure"
    EQUATION = "equation"
    CODE_BLOCK = "code_block"
    EXERCISE = "exercise"
    QUESTION = "question"
    DEFINITION = "definition"
    NOTE = "note"
    CALLOUT = "callout"
    REFERENCE = "reference"
    METADATA_BLOCK = "metadata_block"
    PAGE_BREAK = "page_break"
    PAGE_HEADER = "page_header"
    PAGE_FOOTER = "page_footer"
    TABLE_OF_CONTENTS = "table_of_contents"
    TEXT_ITEM = "text_item"
    FORM_AREA = "form_area"


class HeadingLevel(IntEnum):
    """Standard heading hierarchy.

    Maps to ``DocumentNode.level`` for heading nodes. Higher values indicate
    deeper nesting.
    """

    CHAPTER = 1
    SECTION = 2
    SUBSECTION = 3
    SUBSUBSECTION = 4


class TableOfContentsType(StrEnum):
    """Whether a TOC node is auto-generated or manually curated."""

    AUTO = "auto"
    MANUAL = "manual"


class NoteType(StrEnum):
    """Semantic categories for note nodes."""

    INFO = "info"
    TIP = "tip"
    WARNING = "warning"
    DANGER = "danger"


class CalloutType(StrEnum):
    """Semantic categories for callout nodes."""

    EXAMPLE = "example"
    NON_EXAMPLE = "non_example"
    REMINDER = "reminder"


class ExerciseType(StrEnum):
    """Kinds of exercises."""

    MULTIPLE_CHOICE = "multiple_choice"
    SHORT_ANSWER = "short_answer"
    TRUE_FALSE = "true_false"
    PROBLEM = "problem"


class QuestionType(StrEnum):
    """Canonical question types extracted from structured document content."""

    MULTIPLE_CHOICE = "multiple_choice"
    TRUE_FALSE = "true_false"
    FILL_IN_BLANK = "fill_in_blank"
    SHORT_ANSWER = "short_answer"
    MATCHING = "matching"
    ORDERING = "ordering"
    UNKNOWN = "unknown"


class ListStyle(StrEnum):
    """Visual style of a list."""

    BULLET = "bullet"
    NUMBERED = "numbered"
    ALPHA = "alpha"
    ROMAN = "roman"
    CHECKBOX = "checkbox"


class HorizontalAlignment(StrEnum):
    """Horizontal alignment options."""

    LEFT = "left"
    CENTER = "center"
    RIGHT = "right"
    JUSTIFY = "justify"


class VerticalAlignment(StrEnum):
    """Vertical alignment options for table cells and figures."""

    TOP = "top"
    MIDDLE = "middle"
    BOTTOM = "bottom"


# ──────────────────────────────────────────────────────────────────────────────
# Spatial & Source Models
# ──────────────────────────────────────────────────────────────────────────────


class BoundingBox(BaseModel):
    """Spatial position of a node on a page.

    Coordinates are in points (1 pt = 1/72 inch). Origin is top-left.
    ``width`` and ``height`` default to 0 when unavailable (e.g. for
    block-level elements spanning the full page width).
    """

    x: float = 0.0
    y: float = 0.0
    width: float = 0.0
    height: float = 0.0
    page_width: float = 0.0
    page_height: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceLocation(BaseModel):
    """Position of a node in the original source file.

    ``file`` is the relative or absolute path to the source document.
    ``offset`` and ``length`` are character-level spans within the file
    (useful for plain-text extractions). ``element_ref`` is an opaque
    identifier from the parser (e.g. Docling element ID).
    """

    file: str = ""
    page: int = 0
    offset: int = 0
    length: int = 0
    element_ref: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Styling Models
# ──────────────────────────────────────────────────────────────────────────────


class FontInfo(BaseModel):
    """Font properties for a text span or block."""

    name: str = ""
    size: float = 0.0
    is_bold: bool = False
    is_italic: bool = False
    is_underline: bool = False
    is_strikethrough: bool = False
    color: str = ""
    background_color: str = ""


class InlineStyle(BaseModel):
    """Styling information applied to a ``TextRun``."""

    font: FontInfo = Field(default_factory=FontInfo)
    baseline_shift: float = 0.0
    language: str = ""


class BlockStyle(BaseModel):
    """Styling information applied to a ``DocumentNode``."""

    font: FontInfo = Field(default_factory=FontInfo)
    alignment: HorizontalAlignment = HorizontalAlignment.LEFT
    indent_level: int = 0
    line_spacing: float = 1.0
    space_before: float = 0.0
    space_after: float = 0.0
    background_color: str = ""
    border_color: str = ""
    border_width: float = 0.0
    padding: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Text Content Models
# ──────────────────────────────────────────────────────────────────────────────


class TextRun(BaseModel):
    """A contiguous span of text with uniform styling.

    Multiple ``TextRun`` instances inside a ``Paragraph`` or other text
    block represent inline formatting changes (bold, italic, links, etc.).
    """

    text: str
    style: InlineStyle = Field(default_factory=InlineStyle)
    link_target: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class StyledText(BaseModel):
    """A block of styled text composed of multiple ``TextRun`` segments."""

    runs: list[TextRun] = Field(default_factory=list)
    language: str = ""

    @property
    def plain_text(self) -> str:
        """Concatenate all runs into a single plain-text string."""
        return "".join(run.text for run in self.runs)


# ──────────────────────────────────────────────────────────────────────────────
# Content Block Models — leaf and structural elements
# ──────────────────────────────────────────────────────────────────────────────


class Paragraph(BaseModel):
    """A block of inline text, possibly with mixed styling."""

    type: Literal["paragraph"] = "paragraph"
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class TextItem(BaseModel):
    """A discrete text element, typically a child of a FormAreaBlock.

    Unlike ``Paragraph``, which represents flowing prose, ``TextItem`` models
    individual text fragments such as word-bank choices, form field labels,
    or answer options. Each item is a distinct selectable/fillable unit.
    """

    type: Literal["text_item"] = "text_item"
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Heading(BaseModel):
    """A heading node with an explicit level."""

    type: Literal["heading"] = "heading"
    number: str = ""
    level: HeadingLevel = HeadingLevel.SECTION
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListItem(BaseModel):
    """A single item inside a list.

    ``checked`` is only meaningful for checkbox-style lists.
    """

    text: StyledText = Field(default_factory=StyledText)
    checked: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ListBlock(BaseModel):
    """An ordered or unordered list.

    Children are represented as ``ListItem`` entries in ``items``. Nested
    lists are expressed by placing child ``DocumentNode`` instances inside
    the ``DocumentNode.children`` of the list node.
    """

    type: Literal["list"] = "list"
    style: ListStyle = ListStyle.BULLET
    items: list[ListItem] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class FormAreaBlock(BaseModel):
    """A form area containing interactive or fillable content.

    Represents word banks, answer boxes, option groups, and similar
    interactive regions. Children are ``TextItem`` nodes attached as
    ``DocumentNode.children`` of the form area node.

    The ``display_hint`` field provides rendering guidance to the UI:
    - ``"word_bank"``: horizontal layout of selectable items
    - ``"answer_box"``: bordered input region
    - ``None``: default form area rendering
    """

    type: Literal["form_area"] = "form_area"
    display_hint: Literal["word_bank", "answer_box"] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableCell(BaseModel):
    """A single cell in a table.

    ``row_span`` and ``col_span`` handle merged cells. ``header`` marks
    cells that belong to the table header row.
    """

    content: list[TextRun] = Field(default_factory=list)
    row_span: int = 1
    col_span: int = 1
    header: bool = False
    alignment: HorizontalAlignment = HorizontalAlignment.LEFT
    vertical_alignment: VerticalAlignment = VerticalAlignment.TOP
    style: BlockStyle | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableRow(BaseModel):
    """A row in a table, containing one or more cells."""

    cells: list[TableCell] = Field(default_factory=list)
    is_header: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableBlock(BaseModel):
    """A tabular data structure.

    ``headers`` is a convenience list of header cell texts. Full cell
    metadata (spans, alignment, styling) lives in ``rows``.
    """

    type: Literal["table"] = "table"
    rows: list[TableRow] = Field(default_factory=list)
    headers: list[str] = Field(default_factory=list)
    caption: str = ""
    column_count: int = 0
    row_count: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Figure(BaseModel):
    """A visual figure (image, diagram, chart, etc.).

    ``caption_node_id`` references a sibling ``DocumentNode`` node that
    serves as the figure caption when the caption is a separate node.
    ``caption_text`` stores an inline caption when it is embedded.

    ``image_base64`` holds raw image bytes (pydantic ``Base64Bytes``).
    It is populated in-memory during the pipeline run and stripped before
    persisting to ``lp_documents.nodes`` — images are stored separately
    in ``lp_document_images`` and lazily fetched via the image endpoint.
    """

    type: Literal["figure"] = "figure"
    image_uri: str = ""
    alt_text: str = ""
    caption_text: str = ""
    caption_node_id: UUID | None = None
    width: float = 0.0
    height: float = 0.0
    format: str = ""
    mimetype: str = ""
    storage_key: str = ""
    size_bytes: int = 0
    image_base64: ImageBytes | None = None  # raw bytes in memory; stripped on DB serialization
    metadata: dict[str, Any] = Field(default_factory=dict)


class Equation(BaseModel):
    """A mathematical equation or formula.

    ``latex`` holds the LaTeX source. ``mathml`` optionally holds MathML.
    ``label`` is an equation number or label (e.g. ``"eq. 3.2"``).
    ``is_block`` distinguishes display equations from inline math.
    """

    type: Literal["equation"] = "equation"
    latex: str = ""
    mathml: str = ""
    label: str = ""
    is_block: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class CodeBlock(BaseModel):
    """A verbatim code listing.

    ``language`` enables syntax highlighting. ``filename`` optionally
    records the source file name when the code block was extracted from a
    file listing.
    """

    type: Literal["code_block"] = "code_block"
    code: str = ""
    language: str = ""
    filename: str = ""
    line_start: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class AnswerOption(BaseModel):
    """A single answer choice for a multiple-choice exercise."""

    label: str = ""
    text: StyledText = Field(default_factory=StyledText)
    is_correct: bool = False
    explanation: str = ""


class Exercise(BaseModel):
    """An exercise, question, or problem.

    ``exercise_type`` determines which fields are populated. For
    ``MULTIPLE_CHOICE`` the ``options`` list carries the choices. For
    ``SHORT_ANSWER`` and ``PROBLEM`` the ``solution`` field holds the
    expected answer.
    """

    type: Literal["exercise"] = "exercise"
    exercise_type: ExerciseType = ExerciseType.MULTIPLE_CHOICE
    question: StyledText = Field(default_factory=StyledText)
    options: list[AnswerOption] = Field(default_factory=list)
    solution: str = ""
    explanation: str = ""
    points: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionOption(BaseModel):
    """A single selectable option for multiple-choice style questions."""

    label: str = ""
    text: StyledText = Field(default_factory=StyledText)
    is_correct: bool | None = None
    explanation: str = ""


class FillInBlank(BaseModel):
    """Represents one fill-in-the-blank slot in a question."""

    blank_id: int
    placeholder: str = ""
    answer: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class QuestionStatement(BaseModel):
    """A numbered statement, typically used in true/false sections."""

    number: int | None = None
    text: StyledText = Field(default_factory=StyledText)
    expected_answer: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Question(BaseModel):
    """First-class canonical question content extracted from source documents."""

    type: Literal["question"] = "question"
    question_type: QuestionType = QuestionType.UNKNOWN
    text: StyledText = Field(default_factory=StyledText)
    options: list[QuestionOption] = Field(default_factory=list)
    blanks: list[FillInBlank] = Field(default_factory=list)
    statements: list[QuestionStatement] = Field(default_factory=list)
    solution: str = ""
    explanation: str = ""
    points: float = 0.0
    metadata: dict[str, Any] = Field(default_factory=dict)


class Definition(BaseModel):
    """A term-definition pair.

    ``term`` is the defined term and ``definition`` is the explanatory
    text. ``source_node_id`` links back to the original paragraph or
    section that contained this definition before extraction.
    """

    type: Literal["definition"] = "definition"
    term: str = ""
    definition: str = ""
    source_node_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Note(BaseModel):
    """A margin note, aside, or tip.

    ``note_type`` provides semantic categorization (info, tip, warning,
    danger).
    """

    type: Literal["note"] = "note"
    note_type: NoteType = NoteType.INFO
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Callout(BaseModel):
    """A highlighted callout block (example, non-example, reminder).

    ``callout_type`` distinguishes the purpose of the callout.
    """

    type: Literal["callout"] = "callout"
    callout_type: CalloutType = CalloutType.EXAMPLE
    title: str = ""
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class Reference(BaseModel):
    """A bibliographic or cross-reference entry.

    ``ref_type`` distinguishes ``"bibliographic"`` citations from
    ``"cross"`` references to other parts of the document. ``target_id``
    optionally points to the referenced ``DocumentNode``.
    """

    type: Literal["reference"] = "reference"
    ref_type: str = "bibliographic"
    label: str = ""
    text: str = ""
    target_id: UUID | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MetadataBlock(BaseModel):
    """Inline metadata embedded in the document flow.

    Use this for structured metadata that appears as a visible block in
    the document (e.g. a summary box, key-value table, or attribution
    section). Document-level metadata belongs on ``CanonicalDocument``
    instead.
    """

    type: Literal["metadata_block"] = "metadata_block"
    key: str = ""
    value: str = ""
    entries: dict[str, str] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageBreak(BaseModel):
    """Explicit page break marker."""

    type: Literal["page_break"] = "page_break"
    page_number: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageHeader(BaseModel):
    """Content repeated at the top of each page (running header)."""

    type: Literal["page_header"] = "page_header"
    text: StyledText = Field(default_factory=StyledText)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PageFooter(BaseModel):
    """Content repeated at the bottom of each page (running footer)."""

    type: Literal["page_footer"] = "page_footer"
    text: StyledText = Field(default_factory=StyledText)
    page_number: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class TableOfContentsEntry(BaseModel):
    """A single entry in a table of contents."""

    label: str = ""
    page_number: int = 0
    node_id: UUID | None = None
    indent_level: int = 0


class TableOfContents(BaseModel):
    """A table-of-contents block."""

    type: Literal["table_of_contents"] = "table_of_contents"
    toc_type: TableOfContentsType = TableOfContentsType.AUTO
    entries: list[TableOfContentsEntry] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Discriminated Union
# ──────────────────────────────────────────────────────────────────────────────

ContentBlock = Annotated[
    Paragraph
    | TextItem
    | Heading
    | ListBlock
    | FormAreaBlock
    | TableBlock
    | Figure
    | Equation
    | CodeBlock
    | Exercise
    | Question
    | Definition
    | Note
    | Callout
    | Reference
    | MetadataBlock
    | PageBreak
    | PageHeader
    | PageFooter
    | TableOfContents,
    Field(discriminator="type"),
]


# ──────────────────────────────────────────────────────────────────────────────
# Document Node
# ──────────────────────────────────────────────────────────────────────────────


class DocumentNode(BaseModel):
    """A single node in the canonical document tree.

    Every node carries:

    - **id** — globally unique UUID.
    - **parent_id** — ``None`` only for the root.
    - **children** — ordered child nodes (reading order).
    - **page** — 1-indexed page number.
    - **source** — position in the original file.
    - **bbox** — spatial bounding box on the page.
    - **style** — visual styling information.
    - **content** — the actual payload, a discriminated union of content types.
    - **level** — heading depth (only meaningful for ``Heading`` content).
    - **metadata** — open key-value store for stage-specific data.

    Reading order is determined by the order of ``children`` at each level
    and the order of ``DocumentNode`` entries in ``CanonicalDocument.nodes``.
    """

    id: UUID = Field(default_factory=uuid4)
    parent_id: UUID | None = None
    children: list[DocumentNode] = Field(default_factory=list)

    content: ContentBlock

    page: int = 0
    seq: int = 0
    source: SourceLocation = Field(default_factory=SourceLocation)
    bbox: BoundingBox = Field(default_factory=BoundingBox)
    style: BlockStyle | None = None
    level: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"arbitrary_types_allowed": True}

    def to_string(self) -> str:
        return f" page: {self.page} seq: {self.seq} content: {self.content}"


# ──────────────────────────────────────────────────────────────────────────────
# Document-Level Metadata
# ──────────────────────────────────────────────────────────────────────────────


class DocumentMetadata(BaseModel):
    """Metadata about the source document as a whole.

    Populated by the parser from file properties, PDF info, or document
    headers.
    """

    title: str = ""
    author: str = ""
    subject: str = ""
    keywords: list[str] = Field(default_factory=list)
    creation_date: str = ""
    modification_date: str = ""
    language: str = ""
    page_count: int = 0
    file_size: int = 0
    file_type: str = ""
    checksum: str = ""
    custom: dict[str, Any] = Field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────────────
# Canonical Document (root)
# ──────────────────────────────────────────────────────────────────────────────


class CanonicalDocument(BaseModel):
    """Root document model — the output of Parser, input to all downstream stages.

    The tree is stored in two complementary forms:

    - **``root``** — the top-level ``DocumentNode`` whose ``children``
      form the document's reading-order tree.
    - **``nodes``** — a flat list of *all* ``DocumentNode`` instances
      (pre-order traversal). Used for bulk operations and indexing.

    ``node_map`` is a computed ``UUID → DocumentNode`` lookup dictionary
    built by ``rebuild_index()``. Call ``rebuild_index()`` after mutating
    the tree to keep it in sync.

    Attributes
    ----------
    source : str
        Original file path or URI.
    metadata : DocumentMetadata
        Document-level metadata extracted during parsing.
    nodes : list[DocumentNode]
        Flat list of every node in the document (pre-order).
    node_map : dict[UUID, DocumentNode]
        UUID-based lookup for all nodes. Rebuilt by ``rebuild_index()``.
    """

    source: str = ""
    title: str = ""
    metadata: DocumentMetadata = Field(default_factory=DocumentMetadata)
    nodes: list[DocumentNode] = Field(default_factory=list)
    node_map: dict[UUID, DocumentNode] = Field(default_factory=dict)

    def rebuild_index(self) -> None:
        """Rebuild ``node_map`` and ``self.nodes`` from the tree rooted at
        the first entry in ``nodes`` (assumed to be the root).

        This must be called after any mutation of the tree structure.
        """
        self.node_map.clear()
        if self.nodes:
            root = self.nodes[0]
            self.nodes.clear()
            self._collect_nodes(root, self.nodes)
        for node in self.nodes:
            self.node_map[node.id] = node

    def get_node(self, node_id: UUID) -> DocumentNode | None:
        """Look up a node by UUID. Returns ``None`` if not found."""
        return self.node_map.get(node_id)

    def children_of(self, node_id: UUID) -> list[DocumentNode]:
        """Return the children of a given node, or an empty list."""
        node = self.get_node(node_id)
        if node is None:
            return []
        return [self.get_node(child.id) for child in node.children if child.id in self.node_map]

    def parent_of(self, node_id: UUID) -> DocumentNode | None:
        """Return the parent of a given node, or ``None``."""
        node = self.get_node(node_id)
        if node is None or node.parent_id is None:
            return None
        return self.get_node(node.parent_id)

    def _collect_nodes(self, node: DocumentNode, accumulator: list[DocumentNode]) -> None:
        """Recursively collect all nodes in pre-order into *accumulator*."""
        accumulator.append(node)
        for child in node.children:
            self._collect_nodes(child, accumulator)

    def to_string(self) -> str:
        """Return a string representation of the document, including all nodes."""
        result = ""
        for node in self.nodes:
            result = result + "\n" + node.to_string()
            if node.children:
                result += "\n Children:\n"
                for child in node.children:
                    result = result + "\n" + child.to_string()

        return result


# Rebuild forward references
DocumentNode.model_rebuild()
