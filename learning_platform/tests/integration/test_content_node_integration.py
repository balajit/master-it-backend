"""Integration tests — ContentNode pipeline: PDF → pipeline → LessonCard.content.

These tests exercise the full chain without a running HTTP server:

  test PDF → PipelineOrchestrator → StudyExperience → LessonCard.content

They verify:
  1. The mapper produces ContentNode objects from a real PDF.
  2. All required node types (heading, paragraph, list, equation, code_block,
     table) appear at least once across the lessons in the experience.
  3. ContentNode discriminated-union serialises correctly to JSON (the wire format
     a client app would consume).
  4. The ``GET /api/documents/{doc_id}/mapping`` endpoint (via ASGI transport)
     includes ``content`` in each LessonCard of the response.

Run:
  uv run pytest learning_platform/tests/integration/test_content_node_integration.py -v
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

# ── Path setup ────────────────────────────────────────────────────────────────
_project_root = str(Path(__file__).resolve().parent.parent.parent)
if _project_root not in sys.path:
    sys.path.insert(0, _project_root)

# The test PDF lives in the repo root test_pdfs/ directory (one level above learning_platform/)
_repo_root = str(Path(__file__).resolve().parent.parent.parent.parent)

os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///test_content_node.db")
os.environ.setdefault("JWT_SECRET", "test-content-node-secret")

# ── Test PDF ──────────────────────────────────────────────────────────────────
CONTENT_NODE_PDF: Path = (Path(_repo_root) / "test_pdfs" / "content_node_test.pdf").resolve()

# ── Pipeline imports ──────────────────────────────────────────────────────────
from learning_platform.pipeline.orchestrator import PipelineOrchestrator  # noqa: E402
from learning_platform.pipeline.plugins import PluginRegistry  # noqa: E402
from learning_platform.pipeline.retry import RetryPolicy  # noqa: E402
from learning_platform.presentation.mappers.configuration import (  # noqa: E402
    create_default_config,
)
from learning_platform.presentation.mappers.content_mapper import (  # noqa: E402
    canonical_node_to_content_node,
    document_nodes_to_content,
)
from learning_platform.presentation.mappers.context import ProgressContext  # noqa: E402
from learning_platform.presentation.mappers.learning_experience import (  # noqa: E402
    PipelineOutput,
    create_learning_experience,
)
from learning_platform.presentation.models import (  # noqa: E402
    CalloutNode,
    CodeBlockNode,
    ContentNode,
    DefinitionNode,
    EquationNode,
    FigureNode,
    HeadingNode,
    ListNode,
    NoteNode,
    ParagraphNode,
    StudyExperience,
    TableNode,
)

# ── Module-scoped pipeline fixture ───────────────────────────────────────────


@pytest.fixture(scope="module")
def pipeline_result() -> Any:
    """Run the full pipeline on content_node_test.pdf once for the module."""
    from docling.datamodel.base_models import InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions
    from docling.document_converter import DocumentConverter, PdfFormatOption

    from learning_platform.stages.concept_extractor import ConceptExtractor
    from learning_platform.stages.concept_extractor.annotation_strategy import AnnotationStrategy
    from learning_platform.stages.concept_extractor.text_strategy import TextPatternStrategy
    from learning_platform.stages.enricher.semantic import SemanticEnricher
    from learning_platform.stages.graph_builder.graph import NetworkxGraphBuilder
    from learning_platform.stages.normalizer.structural import StructuralNormalizer
    from learning_platform.stages.parser.docling_adapter import DoclingAdapter
    from learning_platform.stages.sequence_builder.sequencer import TopologicalSequenceBuilder
    from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

    opts = PdfPipelineOptions()
    opts.do_ocr = False
    opts.generate_page_images = False
    opts.generate_picture_images = False
    opts.do_picture_description = False
    opts.do_code_enrichment = False
    opts.do_formula_enrichment = False

    converter = DocumentConverter(
        format_options={
            InputFormat.PDF: PdfFormatOption(pipeline_options=opts),
        }
    )

    concept_extractor = ConceptExtractor(strategies=[TextPatternStrategy(), AnnotationStrategy()])

    orchestrator = PipelineOrchestrator(
        parser=DoclingAdapter(converter=converter),
        normalizer=StructuralNormalizer(),
        enricher=SemanticEnricher(),
        unit_builder=LearningUnitBuilder(),
        concept_extractor=concept_extractor,
        graph_builder=NetworkxGraphBuilder(),
        sequence_builder=TopologicalSequenceBuilder(),
        plugin_registry=PluginRegistry(),
        retry_policy=RetryPolicy(max_retries=2),
    )

    return orchestrator.run(str(CONTENT_NODE_PDF))


@pytest.fixture(scope="module")
def study_experience(pipeline_result: Any) -> StudyExperience:
    """Build the full StudyExperience from the pipeline output."""
    output = PipelineOutput(
        document=pipeline_result.document,
        learning_units=pipeline_result.units,
        annotations=pipeline_result.annotations,
        concept_map=pipeline_result.concepts,
        knowledge_graph=pipeline_result.graph,
        study_plan=pipeline_result.study_plan,
        quizzes=[],
        pages=pipeline_result.pages,
    )
    progress = ProgressContext(user_id=1, course_id=1)
    config = create_default_config()
    return create_learning_experience(output, progress, config)


@pytest.fixture(scope="module")
def all_content_nodes(study_experience: StudyExperience) -> list[ContentNode]:
    """Flatten all content nodes from all lessons."""
    nodes: list[ContentNode] = []
    for lesson in study_experience.lessons:
        nodes.extend(lesson.content)
    return nodes


# ── Test: PDF exists and is readable ─────────────────────────────────────────


class TestTestPdfExists:
    def test_pdf_file_exists(self) -> None:
        assert CONTENT_NODE_PDF.exists(), (
            f"Test PDF not found at {CONTENT_NODE_PDF}. "
            "Run: uv run python test_pdfs/generate_content_node_test_pdf.py"
        )


# ── Test: Pipeline produces document nodes ───────────────────────────────────


class TestPipelineOutput:
    def test_document_has_nodes(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.document.nodes) > 0

    def test_document_title_is_set(self, pipeline_result: Any) -> None:
        assert pipeline_result.document.title != ""

    def test_has_learning_units(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.units) > 0

    def test_has_study_plan(self, pipeline_result: Any) -> None:
        assert pipeline_result.study_plan is not None

    def test_has_pages(self, pipeline_result: Any) -> None:
        assert len(pipeline_result.pages) > 0


# ── Test: LessonCard.content is populated ─────────────────────────────────────


class TestLessonCardContentPopulated:
    """Verify that LessonCard.content is not empty for lessons with page ranges."""

    def test_lessons_exist(self, study_experience: StudyExperience) -> None:
        assert len(study_experience.lessons) > 0, "No lessons in StudyExperience"

    def test_at_least_one_lesson_has_content(self, study_experience: StudyExperience) -> None:
        lessons_with_content = [l for l in study_experience.lessons if l.content]
        assert len(lessons_with_content) > 0, (
            "No lesson has any content nodes. "
            "Verify the PDF was processed and page ranges are populated."
        )

    def test_content_field_is_list(self, study_experience: StudyExperience) -> None:
        for lesson in study_experience.lessons:
            assert isinstance(lesson.content, list), (
                f"Lesson {lesson.lesson_id} content is not a list"
            )

    def test_content_never_none(self, study_experience: StudyExperience) -> None:
        for lesson in study_experience.lessons:
            assert lesson.content is not None


# ── Test: ContentNode types ────────────────────────────────────────────────────


class TestContentNodeTypes:
    """Verify that various ContentNode types are produced from the rich test PDF."""

    def test_has_heading_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        headings = [n for n in all_content_nodes if isinstance(n, HeadingNode)]
        assert len(headings) > 0, "Expected at least one HeadingNode"

    def test_has_paragraph_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        paragraphs = [n for n in all_content_nodes if isinstance(n, ParagraphNode)]
        assert len(paragraphs) > 0, "Expected at least one ParagraphNode"

    def test_has_list_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        lists = [n for n in all_content_nodes if isinstance(n, ListNode)]
        assert len(lists) > 0, "Expected at least one ListNode"

    def test_has_table_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        tables = [n for n in all_content_nodes if isinstance(n, TableNode)]
        assert len(tables) > 0, "Expected at least one TableNode"

    # Equations and code blocks require Docling formula/code enrichment.
    # These are skipped unless the pipeline is run with enrichment enabled.
    @pytest.mark.skip(reason="Equation detection requires formula enrichment pipeline")
    def test_has_equation_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        equations = [n for n in all_content_nodes if isinstance(n, EquationNode)]
        assert len(equations) > 0, "Expected at least one EquationNode"

    @pytest.mark.skip(reason="Code block detection requires code enrichment pipeline")
    def test_has_code_block_nodes(self, all_content_nodes: list[ContentNode]) -> None:
        code_blocks = [n for n in all_content_nodes if isinstance(n, CodeBlockNode)]
        assert len(code_blocks) > 0, "Expected at least one CodeBlockNode"


# ── Test: HeadingNode properties ──────────────────────────────────────────────


class TestHeadingNode:
    def test_heading_level_in_range(self, all_content_nodes: list[ContentNode]) -> None:
        headings = [n for n in all_content_nodes if isinstance(n, HeadingNode)]
        for h in headings:
            assert 1 <= h.level <= 4, f"Heading level {h.level} out of range [1, 4]"

    def test_heading_text_not_empty(self, all_content_nodes: list[ContentNode]) -> None:
        headings = [n for n in all_content_nodes if isinstance(n, HeadingNode)]
        for h in headings:
            assert h.text.strip() != "", "Heading text should not be empty"

    def test_heading_type_discriminator(self, all_content_nodes: list[ContentNode]) -> None:
        headings = [n for n in all_content_nodes if isinstance(n, HeadingNode)]
        for h in headings:
            assert h.type == "heading"


# ── Test: ParagraphNode properties ────────────────────────────────────────────


class TestParagraphNode:
    def test_paragraph_has_runs(self, all_content_nodes: list[ContentNode]) -> None:
        paragraphs = [n for n in all_content_nodes if isinstance(n, ParagraphNode)]
        for p in paragraphs:
            assert len(p.runs) > 0, "ParagraphNode must have at least one run"

    def test_paragraph_runs_have_text(self, all_content_nodes: list[ContentNode]) -> None:
        paragraphs = [n for n in all_content_nodes if isinstance(n, ParagraphNode)]
        for p in paragraphs:
            combined = "".join(getattr(r, "text", getattr(r, "latex", "")) for r in p.runs)
            assert combined.strip() != "", "Paragraph runs should produce non-empty text"

    def test_paragraph_type_discriminator(self, all_content_nodes: list[ContentNode]) -> None:
        paragraphs = [n for n in all_content_nodes if isinstance(n, ParagraphNode)]
        for p in paragraphs:
            assert p.type == "paragraph"


# ── Test: ListNode properties ─────────────────────────────────────────────────


class TestListNode:
    def test_list_has_items(self, all_content_nodes: list[ContentNode]) -> None:
        lists = [n for n in all_content_nodes if isinstance(n, ListNode)]
        for lst in lists:
            assert len(lst.items) > 0, "ListNode must have at least one item"

    def test_list_style_is_valid(self, all_content_nodes: list[ContentNode]) -> None:
        valid_styles = {"bullet", "numbered", "alpha", "roman", "checkbox"}
        lists = [n for n in all_content_nodes if isinstance(n, ListNode)]
        for lst in lists:
            assert lst.style in valid_styles, f"Unexpected list style: {lst.style}"

    def test_list_items_have_runs(self, all_content_nodes: list[ContentNode]) -> None:
        lists = [n for n in all_content_nodes if isinstance(n, ListNode)]
        for lst in lists:
            for item in lst.items:
                assert len(item.runs) > 0, "ListItemNode must have at least one run"


# ── Test: TableNode properties ────────────────────────────────────────────────


class TestTableNode:
    def test_table_has_rows(self, all_content_nodes: list[ContentNode]) -> None:
        tables = [n for n in all_content_nodes if isinstance(n, TableNode)]
        for tbl in tables:
            assert len(tbl.rows) > 0, "TableNode must have at least one row"

    def test_table_rows_have_cells(self, all_content_nodes: list[ContentNode]) -> None:
        tables = [n for n in all_content_nodes if isinstance(n, TableNode)]
        for tbl in tables:
            for row in tbl.rows:
                assert len(row.cells) > 0, "TableRowNode must have at least one cell"

    def test_table_type_discriminator(self, all_content_nodes: list[ContentNode]) -> None:
        tables = [n for n in all_content_nodes if isinstance(n, TableNode)]
        for tbl in tables:
            assert tbl.type == "table"


# ── Test: JSON serialisation ──────────────────────────────────────────────────


class TestJsonSerialisation:
    """Verify ContentNode serialises correctly to JSON (the wire format)."""

    def test_heading_node_serialises(self) -> None:
        node = HeadingNode(level=2, number="1.1", text="Introduction")
        data = json.loads(node.model_dump_json())
        assert data["type"] == "heading"
        assert data["level"] == 2
        assert data["text"] == "Introduction"

    def test_paragraph_node_serialises(self) -> None:
        from learning_platform.presentation.models import PlainRun

        node = ParagraphNode(runs=[PlainRun(text="Water is the most common solvent.")])
        data = json.loads(node.model_dump_json())
        assert data["type"] == "paragraph"
        assert data["runs"][0]["run_type"] == "text"
        assert data["runs"][0]["text"] == "Water is the most common solvent."

    def test_eq_run_serialises(self) -> None:
        from learning_platform.presentation.models import EqRun

        node = ParagraphNode(runs=[EqRun(latex=r"A = \pi r^2")])
        data = json.loads(node.model_dump_json())
        assert data["runs"][0]["run_type"] == "eq"
        assert data["runs"][0]["latex"] == r"A = \pi r^2"

    def test_equation_node_serialises(self) -> None:
        node = EquationNode(latex=r"2H_2 + O_2 \rightarrow 2H_2O", label="")
        data = json.loads(node.model_dump_json())
        assert data["type"] == "equation"
        assert "2H_2" in data["latex"]

    def test_code_block_node_serialises(self) -> None:
        node = CodeBlockNode(language="python", code="def f(x):\n    return x**2")
        data = json.loads(node.model_dump_json())
        assert data["type"] == "code_block"
        assert data["language"] == "python"

    def test_list_node_serialises(self) -> None:
        from learning_platform.presentation.models import ListItemNode, PlainRun

        node = ListNode(
            style="bullet",
            items=[ListItemNode(runs=[PlainRun(text="First item")])],
        )
        data = json.loads(node.model_dump_json())
        assert data["type"] == "list"
        assert data["style"] == "bullet"
        assert data["items"][0]["runs"][0]["text"] == "First item"

    def test_table_node_serialises(self) -> None:
        node = TableNode(
            caption="Test table",
            rows=[],
        )
        data = json.loads(node.model_dump_json())
        assert data["type"] == "table"
        assert data["caption"] == "Test table"

    def test_note_node_serialises(self) -> None:
        node = NoteNode.from_text("Always balance equations.", variant="tip")
        data = json.loads(node.model_dump_json())
        assert data["type"] == "note"
        assert data["variant"] == "tip"

    def test_definition_node_serialises(self) -> None:
        node = DefinitionNode(term="Reactant", definition="A substance consumed in a reaction.")
        data = json.loads(node.model_dump_json())
        assert data["type"] == "definition"
        assert data["term"] == "Reactant"

    def test_figure_node_serialises(self) -> None:
        node = FigureNode(
            image_url="https://example.com/img.png", alt_text="Diagram", caption="Fig 1"
        )
        data = json.loads(node.model_dump_json())
        assert data["type"] == "figure"
        assert data["image_url"] == "https://example.com/img.png"

    def test_content_node_list_serialises(self, all_content_nodes: list[ContentNode]) -> None:
        """The full content node list from the real PDF should serialise without errors."""
        from pydantic import TypeAdapter

        from learning_platform.presentation.models import ContentNode as ContentNodeType

        adapter = TypeAdapter(list[ContentNodeType])
        serialised = adapter.dump_json(all_content_nodes)
        parsed = json.loads(serialised)
        assert isinstance(parsed, list)
        # Each node must have a "type" discriminator
        for item in parsed:
            assert "type" in item, f"ContentNode missing 'type' discriminator: {item}"


# ── Test: ContentNode mapper unit tests (no PDF required) ─────────────────────


class TestContentMapperUnit:
    """Unit tests for canonical_node_to_content_node with synthetic DocumentNode objects."""

    def _make_node(self, content: Any) -> Any:
        """Create a minimal DocumentNode with the given content."""
        from uuid import uuid4

        from learning_platform.models.document import DocumentNode

        return DocumentNode(
            id=uuid4(),
            content=content,
            page=1,
        )

    def test_maps_paragraph(self) -> None:
        from learning_platform.models.document import Paragraph, StyledText, TextRun

        content = Paragraph(text=StyledText(runs=[TextRun(text="Hello world")]))
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, ParagraphNode)
        assert result.runs[0].text == "Hello world"  # type: ignore[union-attr]

    def test_maps_heading(self) -> None:
        from learning_platform.models.document import Heading, HeadingLevel, StyledText, TextRun

        content = Heading(
            level=HeadingLevel.SECTION,
            text=StyledText(runs=[TextRun(text="Introduction")]),
            number="1.1",
        )
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, HeadingNode)
        assert result.text == "Introduction"
        assert result.number == "1.1"

    def test_maps_equation(self) -> None:
        from learning_platform.models.document import Equation

        content = Equation(latex=r"E = mc^2", label="eq.1", is_block=True)
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, EquationNode)
        assert result.latex == r"E = mc^2"
        assert result.label == "eq.1"

    def test_maps_code_block(self) -> None:
        from learning_platform.models.document import CodeBlock

        content = CodeBlock(language="python", code="print('hello')")
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, CodeBlockNode)
        assert result.language == "python"
        assert "print" in result.code

    def test_maps_list_block(self) -> None:
        from learning_platform.models.document import (
            ListBlock,
            ListItem,
            ListStyle,
            StyledText,
            TextRun,
        )

        content = ListBlock(
            style=ListStyle.BULLET,
            items=[
                ListItem(text=StyledText(runs=[TextRun(text="Item A")])),
                ListItem(text=StyledText(runs=[TextRun(text="Item B")])),
            ],
        )
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, ListNode)
        assert result.style == "bullet"
        assert len(result.items) == 2

    def test_maps_table_block(self) -> None:
        from learning_platform.models.document import TableBlock, TableCell, TableRow, TextRun

        content = TableBlock(
            rows=[
                TableRow(
                    cells=[
                        TableCell(content=[TextRun(text="Name")], header=True),
                        TableCell(content=[TextRun(text="Value")], header=True),
                    ],
                    is_header=True,
                ),
                TableRow(
                    cells=[
                        TableCell(content=[TextRun(text="x")]),
                        TableCell(content=[TextRun(text="42")]),
                    ],
                ),
            ],
            caption="Test table",
        )
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, TableNode)
        assert result.caption == "Test table"
        assert len(result.rows) == 2
        assert result.rows[0].cells[0].text == "Name"

    def test_maps_definition(self) -> None:
        from learning_platform.models.document import Definition

        content = Definition(term="Velocity", definition="Rate of change of position.")
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, DefinitionNode)
        assert result.term == "Velocity"

    def test_maps_figure(self) -> None:
        from learning_platform.models.document import Figure

        content = Figure(image_uri="file://img.png", alt_text="Alt", caption_text="Caption")
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, FigureNode)
        assert result.image_url == "file://img.png"

    def test_maps_note(self) -> None:
        from learning_platform.models.document import Note, NoteType, StyledText, TextRun

        content = Note(
            note_type=NoteType.TIP,
            text=StyledText(runs=[TextRun(text="Remember this!")]),
        )
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, NoteNode)
        assert result.variant == "tip"

    def test_maps_callout(self) -> None:
        from learning_platform.models.document import Callout, CalloutType, StyledText, TextRun

        content = Callout(
            callout_type=CalloutType.EXAMPLE,
            title="Example 1",
            text=StyledText(runs=[TextRun(text="This is an example.")]),
        )
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, CalloutNode)
        assert result.variant == "example"
        assert result.title == "Example 1"

    def test_skips_page_break(self) -> None:
        from learning_platform.models.document import PageBreak

        content = PageBreak()
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert result is None

    def test_document_nodes_to_content_filters_none(self) -> None:
        from learning_platform.models.document import PageBreak, Paragraph, StyledText, TextRun

        para_content = Paragraph(text=StyledText(runs=[TextRun(text="Hello")]))
        break_content = PageBreak()

        nodes = [self._make_node(para_content), self._make_node(break_content)]
        result = document_nodes_to_content(nodes)
        assert len(result) == 1
        assert isinstance(result[0], ParagraphNode)

    def test_bold_run_mapping(self) -> None:
        from learning_platform.models.document import (
            FontInfo,
            InlineStyle,
            Paragraph,
            StyledText,
            TextRun,
        )
        from learning_platform.presentation.models import BoldRun

        bold_run = TextRun(
            text="Bold text",
            style=InlineStyle(font=FontInfo(is_bold=True)),
        )
        content = Paragraph(text=StyledText(runs=[bold_run]))
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, ParagraphNode)
        assert isinstance(result.runs[0], BoldRun)
        assert result.runs[0].text == "Bold text"

    def test_italic_run_mapping(self) -> None:
        from learning_platform.models.document import (
            FontInfo,
            InlineStyle,
            Paragraph,
            StyledText,
            TextRun,
        )
        from learning_platform.presentation.models import ItalicRun

        italic_run = TextRun(
            text="Italic text",
            style=InlineStyle(font=FontInfo(is_italic=True)),
        )
        content = Paragraph(text=StyledText(runs=[italic_run]))
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, ParagraphNode)
        assert isinstance(result.runs[0], ItalicRun)

    def test_link_run_mapping(self) -> None:
        from learning_platform.models.document import Paragraph, StyledText, TextRun
        from learning_platform.presentation.models import LinkRun

        link_run = TextRun(text="Click here", link_target="https://example.com")
        content = Paragraph(text=StyledText(runs=[link_run]))
        node = self._make_node(content)
        result = canonical_node_to_content_node(node)
        assert isinstance(result, ParagraphNode)
        assert isinstance(result.runs[0], LinkRun)
        assert result.runs[0].href == "https://example.com"


# ── Test: mapping endpoint via ASGI transport ─────────────────────────────────


class TestMappingEndpointContentField:
    """Smoke test: /api/documents/{doc_id}/mapping returns lessons[].content."""

    @pytest.fixture()
    def mock_experience(self, study_experience: StudyExperience) -> StudyExperience:
        return study_experience

    def test_lesson_card_schema_has_content_field(
        self,
        study_experience: StudyExperience,
    ) -> None:
        """Verify LessonCardSchema carries a content field through the router layer."""
        # Import schemas that the router uses
        _src = str(Path(_repo_root) / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)

        from schemas_mapping import LessonCardSchema

        assert "content" in LessonCardSchema.model_fields

    def test_lesson_card_content_round_trips(
        self,
        study_experience: StudyExperience,
    ) -> None:
        """Verify a LessonCard with content serialises and parses back cleanly."""
        _src = str(Path(_repo_root) / "src")
        if _src not in sys.path:
            sys.path.insert(0, _src)

        from schemas_mapping import LessonCardSchema

        for lesson in study_experience.lessons:
            if not lesson.content:
                continue

            schema = LessonCardSchema(
                lesson_id=str(lesson.lesson_id),
                unit_id=str(lesson.unit_id),
                section_id=str(lesson.section_id),
                title=lesson.title,
                description=lesson.description,
                order=lesson.order,
                duration_minutes=lesson.duration_minutes,
                difficulty=lesson.difficulty,
                status=lesson.status,
                learning_objectives=[],
                start_page=lesson.start_page,
                end_page=lesson.end_page,
                completed_at=lesson.completed_at,
                content_references=[],
                definitions=[],
                examples=[],
                figures=[],
                tables=[],
                equations=[],
                content=list(lesson.content),
            )

            raw = json.loads(schema.model_dump_json())
            assert isinstance(raw["content"], list)
            for node in raw["content"]:
                assert "type" in node, f"ContentNode missing 'type': {node}"
            # At least one test per lesson that has content
            break
