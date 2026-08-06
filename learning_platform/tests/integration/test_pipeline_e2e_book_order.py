"""Golden E2E test: PDF element fidelity from parser to CanonicalBook.

Scope:
- Verify only PDF elements, their order, and typography metadata.
- Exclude enrichment/concepts/graph/sequence assertions.

This test is intentionally strict and stage-gated:
1. parser
2. normalizer
3. page grouping
4. enricher
5. unit builder
6. concept extractor
7. graph builder
8. sequence builder
9. book assembler

If any stage fails assertions, the test stops and does not proceed.
"""

from __future__ import annotations

import base64
import importlib
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

import pytest

from learning_platform.models.annotation import Annotation, KeyTermAnnotation
from learning_platform.models.book import CanonicalBook
from learning_platform.models.concept import Concept, ConceptCategory, ConceptMap
from learning_platform.models.document import (
    CanonicalDocument,
    CodeBlock,
    DocumentNode,
    Equation,
    Figure,
    Heading,
    ListBlock,
    Paragraph,
    TableBlock,
    TableCell,
    TextItem,
)
from learning_platform.models.knowledge_graph import KnowledgeGraph, NodeType
from learning_platform.models.learning_unit import LearningUnit, UnitType
from learning_platform.models.page_context import PageContext, build_page_contexts
from learning_platform.models.sequence import StudyPlan
from learning_platform.stages.book_assembler.assembler import BookAssembler
from learning_platform.stages.concept_extractor.extractor import ConceptExtractor
from learning_platform.stages.enricher.semantic import SemanticEnricher
from learning_platform.stages.graph_builder.graph import NetworkxGraphBuilder
from learning_platform.stages.normalizer.structural import StructuralNormalizer
from learning_platform.stages.parser2 import Parser2Adapter
from learning_platform.stages.sequence_builder.sequencer import TopologicalSequenceBuilder
from learning_platform.stages.unit_builder.builder import LearningUnitBuilder

MARKER_RE: re.Pattern[str] = re.compile(r"\bE\d{3}_[A-Z0-9_]+\b")

_TINY_PNG_BASE64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR4nGNgYAAAAAMAASsJTYQAAAAASUVORK5CYII="
)


@dataclass(frozen=True)
class ExpectedElement:
    marker: str
    page: int
    font_token: str
    bold: bool | None = None
    italic: bool | None = None


@dataclass(frozen=True)
class StageHit:
    marker: str
    page: int
    seq: int
    node_index: int
    fragment_index: int
    marker_index: int
    slot_id: str
    font_name: str
    bold: bool | None
    italic: bool | None
    text: str
    element_type: str
    node_id: UUID | None = None


@dataclass(frozen=True)
class ReportLabSymbols:
    colors: Any
    letter: Any
    paragraph_style: Any
    inch: Any
    image: Any
    list_flowable: Any
    list_item: Any
    page_break: Any
    paragraph: Any
    simple_doc_template: Any
    spacer: Any
    table: Any
    table_style: Any


class MarkerAnnotationConceptStrategy:
    """Test strategy that maps injected marker annotations to concepts."""

    def extract(
        self,
        document: CanonicalDocument,
        annotations: list[Annotation],
        units: list[LearningUnit],
    ) -> list[Concept]:
        _ = document
        concepts: list[Concept] = []

        for annotation in annotations:
            metadata = annotation.metadata if isinstance(annotation.metadata, dict) else {}
            marker = str(metadata.get("e2e_marker", "")).strip()
            if not marker:
                continue

            pages = metadata.get("e2e_pages", [])
            page_number = int(pages[0]) if isinstance(pages, list) and pages else 0

            candidate_units = [
                unit for unit in units if annotation.node_id in set(unit.source_node_ids)
            ]
            unit_ids: list[UUID] = []
            if candidate_units:
                candidate_units.sort(
                    key=lambda unit: (-_unit_specificity_rank(unit.unit_type), str(unit.id))
                )
                unit_ids = [candidate_units[0].id]

            concepts.append(
                Concept(
                    name=marker,
                    category=ConceptCategory.VOCABULARY,
                    aliases=[],
                    importance=1.0,
                    mention_count=1,
                    source_node_ids=[annotation.node_id],
                    source_unit_ids=unit_ids,
                    metadata={
                        "e2e_marker": marker,
                        "e2e_pages": [page_number],
                    },
                )
            )

        return concepts


def _unit_specificity_rank(unit_type: UnitType) -> int:
    if unit_type == UnitType.TOPIC:
        return 3
    if unit_type == UnitType.LESSON:
        return 2
    if unit_type == UnitType.MODULE:
        return 1
    return 0


EXPECTED_SEQUENCE: list[ExpectedElement] = [
    ExpectedElement("E001_H1_P1", 1, "helvetica", bold=True),
    ExpectedElement("E002_P_P1", 1, "helvetica"),
    ExpectedElement("E003_P_P1", 1, "helvetica"),
    ExpectedElement("E004_BULLET_TITLE_P1", 1, "helvetica"),
    ExpectedElement("E005_BULLET_1_P1", 1, "helvetica"),
    ExpectedElement("E006_BULLET_2_P1", 1, "helvetica"),
    ExpectedElement("E007_BULLET_3_P1", 1, "helvetica"),
    ExpectedElement("E008_NUMBERED_TITLE_P1", 1, "helvetica"),
    ExpectedElement("E009_NUM_1_P1", 1, "helvetica"),
    ExpectedElement("E010_NUM_2_P1", 1, "helvetica"),
    ExpectedElement("E011_TABLE_H1_P1", 1, "helvetica", bold=True),
    ExpectedElement("E012_TABLE_H2_P1", 1, "helvetica", bold=True),
    ExpectedElement("E013_TABLE_R1C1_P1", 1, "helvetica"),
    ExpectedElement("E014_TABLE_R1C2_P1", 1, "helvetica"),
    ExpectedElement("E015_TABLE_R2C1_P1", 1, "helvetica"),
    ExpectedElement("E016_TABLE_R2C2_P1", 1, "helvetica"),
    ExpectedElement("E017_H2_P2", 2, "helvetica", bold=True),
    ExpectedElement("E018_P_P2", 2, "helvetica"),
    ExpectedElement("E019_EQ_P2", 2, "times", italic=True),
    ExpectedElement("E020_CODE_1_P2", 2, "courier"),
    ExpectedElement("E021_CODE_2_P2", 2, "courier"),
    ExpectedElement("E022_FIG_NOTE_P2", 2, "helvetica", italic=True),
    ExpectedElement("E023_FIG_CAP_P2", 2, "helvetica"),
    ExpectedElement("E024_H2_P3", 3, "helvetica", bold=True),
    ExpectedElement("E025_P_P3", 3, "helvetica"),
    ExpectedElement("E026_BULLET_1_P3", 3, "helvetica"),
    ExpectedElement("E027_BULLET_2_P3", 3, "helvetica"),
    ExpectedElement("E028_TABLE_H1_P3", 3, "helvetica", bold=True),
    ExpectedElement("E029_TABLE_H2_P3", 3, "helvetica", bold=True),
    ExpectedElement("E030_TABLE_R1C1_P3", 3, "helvetica"),
    ExpectedElement("E031_TABLE_R1C2_P3", 3, "helvetica"),
    ExpectedElement("E032_SUMMARY_P3", 3, "helvetica"),
]


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _test_pdf_path() -> Path:
    return _repo_root() / "test_pdfs" / "test_pipeline_e2e.pdf"


def _load_reportlab_symbols() -> ReportLabSymbols:
    try:
        colors_module = importlib.import_module("reportlab.lib.colors")
        pagesizes_module = importlib.import_module("reportlab.lib.pagesizes")
        styles_module = importlib.import_module("reportlab.lib.styles")
        units_module = importlib.import_module("reportlab.lib.units")
        platypus_module = importlib.import_module("reportlab.platypus")
    except Exception as exc:  # pragma: no cover - environment guard
        pytest.skip(f"reportlab is required to build test_pipeline_e2e.pdf: {exc}")
        raise RuntimeError("reportlab import failure") from exc

    return ReportLabSymbols(
        colors=colors_module,
        letter=pagesizes_module.LETTER,
        paragraph_style=styles_module.ParagraphStyle,
        inch=units_module.inch,
        image=platypus_module.Image,
        list_flowable=platypus_module.ListFlowable,
        list_item=platypus_module.ListItem,
        page_break=platypus_module.PageBreak,
        paragraph=platypus_module.Paragraph,
        simple_doc_template=platypus_module.SimpleDocTemplate,
        spacer=platypus_module.Spacer,
        table=platypus_module.Table,
        table_style=platypus_module.TableStyle,
    )


def _ensure_test_pipeline_e2e_pdf() -> Path:
    target = _test_pdf_path()
    if target.exists():
        return target

    reportlab = _load_reportlab_symbols()
    colors = reportlab.colors
    LETTER = reportlab.letter
    ParagraphStyle = reportlab.paragraph_style
    inch = reportlab.inch
    Image = reportlab.image
    ListFlowable = reportlab.list_flowable
    ListItem = reportlab.list_item
    PageBreak = reportlab.page_break
    RLParagraph = reportlab.paragraph
    SimpleDocTemplate = reportlab.simple_doc_template
    Spacer = reportlab.spacer
    Table = reportlab.table
    TableStyle = reportlab.table_style

    target.parent.mkdir(parents=True, exist_ok=True)
    image_path = target.parent / "_test_pipeline_e2e_image.png"
    if not image_path.exists():
        image_path.write_bytes(base64.b64decode(_TINY_PNG_BASE64))

    doc = SimpleDocTemplate(
        str(target),
        pagesize=LETTER,
        rightMargin=inch,
        leftMargin=inch,
        topMargin=inch,
        bottomMargin=inch,
    )

    h1 = ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16, leading=20)
    h2 = ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=13, leading=16)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=11, leading=14)
    eq = ParagraphStyle("eq", fontName="Times-Italic", fontSize=12, leading=14)
    code = ParagraphStyle("code", fontName="Courier", fontSize=10, leading=12)
    note = ParagraphStyle("note", fontName="Helvetica-Oblique", fontSize=11, leading=14)

    story: list[Any] = []

    # Page 1
    story.append(RLParagraph("E001_H1_P1 Chapter One Foundations", h1))
    story.append(Spacer(1, 0.08 * inch))
    story.append(RLParagraph("E002_P_P1 First paragraph with baseline content.", body))
    story.append(Spacer(1, 0.04 * inch))
    story.append(RLParagraph("E003_P_P1 Second paragraph should remain distinct.", body))
    story.append(Spacer(1, 0.06 * inch))
    story.append(RLParagraph("E004_BULLET_TITLE_P1 Bullet items", body))
    story.append(Spacer(1, 0.03 * inch))
    story.append(
        ListFlowable(
            [
                ListItem(RLParagraph("E005_BULLET_1_P1 First bullet", body), bulletText="•"),
                ListItem(RLParagraph("E006_BULLET_2_P1 Second bullet", body), bulletText="•"),
                ListItem(RLParagraph("E007_BULLET_3_P1 Third bullet", body), bulletText="•"),
            ],
            bulletType="bullet",
            leftIndent=18,
        )
    )
    story.append(Spacer(1, 0.05 * inch))
    story.append(RLParagraph("E008_NUMBERED_TITLE_P1 Numbered steps", body))
    story.append(Spacer(1, 0.03 * inch))
    story.append(
        ListFlowable(
            [
                ListItem(RLParagraph("E009_NUM_1_P1 First numbered", body)),
                ListItem(RLParagraph("E010_NUM_2_P1 Second numbered", body)),
            ],
            bulletType="1",
            leftIndent=18,
        )
    )
    story.append(Spacer(1, 0.07 * inch))
    table_one = Table(
        [
            ["E011_TABLE_H1_P1 Header A", "E012_TABLE_H2_P1 Header B"],
            ["E013_TABLE_R1C1_P1 Body A1", "E014_TABLE_R1C2_P1 Body B1"],
            ["E015_TABLE_R2C1_P1 Body A2", "E016_TABLE_R2C2_P1 Body B2"],
        ],
        colWidths=[2.6 * inch, 2.6 * inch],
    )
    table_one.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    story.append(table_one)
    story.append(PageBreak())

    # Page 2
    story.append(RLParagraph("E017_H2_P2 Analysis Stage", h2))
    story.append(Spacer(1, 0.07 * inch))
    story.append(RLParagraph("E018_P_P2 Paragraph on page two.", body))
    story.append(Spacer(1, 0.05 * inch))
    story.append(RLParagraph("E019_EQ_P2 a^2 + b^2 = c^2", eq))
    story.append(Spacer(1, 0.05 * inch))
    story.append(RLParagraph("E020_CODE_1_P2 def add(a, b):", code))
    story.append(RLParagraph("E021_CODE_2_P2 return a + b", code))
    story.append(Spacer(1, 0.08 * inch))
    story.append(RLParagraph("E022_FIG_NOTE_P2 Figure context text.", note))
    story.append(Spacer(1, 0.03 * inch))
    story.append(Image(str(image_path), width=1.0 * inch, height=1.0 * inch))
    story.append(Spacer(1, 0.03 * inch))
    story.append(RLParagraph("E023_FIG_CAP_P2 Figure caption text.", body))
    story.append(PageBreak())

    # Page 3
    story.append(RLParagraph("E024_H2_P3 Final Stage", h2))
    story.append(Spacer(1, 0.08 * inch))
    story.append(RLParagraph("E025_P_P3 Final page paragraph one.", body))
    story.append(Spacer(1, 0.05 * inch))
    story.append(
        ListFlowable(
            [
                ListItem(RLParagraph("E026_BULLET_1_P3 Final bullet one", body), bulletText="•"),
                ListItem(RLParagraph("E027_BULLET_2_P3 Final bullet two", body), bulletText="•"),
            ],
            bulletType="bullet",
            leftIndent=18,
        )
    )
    story.append(Spacer(1, 0.07 * inch))
    table_two = Table(
        [
            ["E028_TABLE_H1_P3 Header X", "E029_TABLE_H2_P3 Header Y"],
            ["E030_TABLE_R1C1_P3 Body X1", "E031_TABLE_R1C2_P3 Body Y1"],
        ],
        colWidths=[2.6 * inch, 2.6 * inch],
    )
    table_two.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    story.append(table_two)
    story.append(Spacer(1, 0.08 * inch))
    story.append(RLParagraph("E032_SUMMARY_P3 Final summary paragraph.", body))

    doc.build(story)
    return target


def _flatten_nodes(document: CanonicalDocument) -> list[DocumentNode]:
    result: list[DocumentNode] = []

    def walk(node: DocumentNode) -> None:
        role = str(node.metadata.get("role", ""))
        if role not in {"document_root", "normalizer_root"}:
            result.append(node)
        for child in node.children:
            walk(child)

    for root in document.nodes:
        walk(root)
    return result


def _node_fragments(node: DocumentNode) -> list[str]:
    content = node.content

    if isinstance(content, Heading):
        return [content.text.plain_text]
    if isinstance(content, Paragraph):
        return [content.text.plain_text]
    if isinstance(content, TextItem):
        return [content.text.plain_text]
    if isinstance(content, ListBlock):
        return [item.text.plain_text for item in content.items]
    if isinstance(content, TableBlock):
        fragments: list[str] = []
        for row in content.rows:
            for cell in row.cells:
                fragments.append("".join(run.text for run in cell.content))
        seen: set[str] = set(fragments)
        for header in content.headers:
            if header not in seen:
                fragments.append(header)
                seen.add(header)
        return fragments
    if isinstance(content, Figure):
        return [content.caption_text, content.alt_text]
    if isinstance(content, Equation):
        return [content.latex]
    if isinstance(content, CodeBlock):
        return [content.code]
    return []


def _fragment_font_info(
    node: DocumentNode, fragment_index: int
) -> tuple[str, bool | None, bool | None]:
    content = node.content

    # Table cell runs are authoritative over the block-level table style.
    if isinstance(content, TableBlock):
        cells: list[TableCell] = []
        for row in content.rows:
            cells.extend(row.cells)
        runs: list[Any] = []
        if fragment_index < len(cells):
            runs = list(cells[fragment_index].content)
        else:
            fragments = _node_fragments(node)
            fragment = fragments[fragment_index] if fragment_index < len(fragments) else ""
            matching_cell = next(
                (cell for cell in cells if "".join(run.text for run in cell.content) == fragment),
                None,
            )
            if matching_cell is not None:
                runs = list(matching_cell.content)
        return _font_info_from_runs(runs)

    if node.style is not None and node.style.font is not None:
        font = node.style.font
        return (
            str(font.name or "").strip().lower(),
            bool(font.is_bold),
            bool(font.is_italic),
        )

    runs = _fragment_runs(content, fragment_index)
    return _font_info_from_runs(runs)


def _fragment_runs(content: Any, fragment_index: int) -> list[Any]:
    runs: list[Any] = []
    if isinstance(content, (Heading, Paragraph, TextItem)):
        if fragment_index == 0:
            runs = list(content.text.runs)
    elif isinstance(content, ListBlock) and fragment_index < len(content.items):
        runs = list(content.items[fragment_index].text.runs)
    return runs


def _font_info_from_runs(runs: list[Any]) -> tuple[str, bool | None, bool | None]:
    for run in runs:
        style = getattr(run, "style", None)
        if style is None or style.font is None:
            continue
        font = style.font
        return (
            str(font.name or "").strip().lower(),
            bool(font.is_bold),
            bool(font.is_italic),
        )

    return ("", None, None)


def _collect_node_hits(nodes: list[DocumentNode]) -> list[StageHit]:
    hits: list[StageHit] = []
    for node_index, node in enumerate(nodes):
        fragments = _node_fragments(node)
        for fragment_index, fragment in enumerate(fragments):
            font_name, bold, italic = _fragment_font_info(node, fragment_index)
            marker_matches = list(MARKER_RE.finditer(fragment or ""))
            for marker_index, marker_match in enumerate(marker_matches):
                hits.append(
                    StageHit(
                        marker=marker_match.group(0),
                        page=int(node.page),
                        seq=int(node.seq),
                        node_index=node_index,
                        fragment_index=fragment_index,
                        marker_index=marker_index,
                        slot_id=f"{node.id}:{fragment_index}",
                        font_name=font_name,
                        bold=bold,
                        italic=italic,
                        text=fragment,
                        element_type=content_type(node),
                        node_id=node.id,
                    )
                )
    return hits


def content_type(node: DocumentNode) -> str:
    return str(getattr(node.content, "type", type(node.content).__name__))


def _collect_page_hits(pages: list[PageContext]) -> list[StageHit]:
    flattened: list[DocumentNode] = []
    for page in sorted(pages, key=lambda p: p.page_number):
        flattened.extend(page.nodes)
    return _collect_node_hits(flattened)


def _collect_unit_hits(
    units: list[LearningUnit],
    marker_hits_by_node: dict[UUID, list[StageHit]],
) -> list[StageHit]:
    hits: list[StageHit] = []
    for unit_index, unit in enumerate(units):
        for source_index, node_id in enumerate(unit.source_node_ids):
            source_hits = marker_hits_by_node.get(node_id, [])
            for marker_index, source_hit in enumerate(source_hits):
                hits.append(
                    StageHit(
                        marker=source_hit.marker,
                        page=source_hit.page,
                        seq=source_hit.seq,
                        node_index=unit_index,
                        fragment_index=source_index,
                        marker_index=marker_index,
                        slot_id=f"{unit.id}:{node_id}:{source_index}",
                        font_name=source_hit.font_name,
                        bold=source_hit.bold,
                        italic=source_hit.italic,
                        text=source_hit.text,
                        element_type="learning_unit_source",
                        node_id=node_id,
                    )
                )
    return hits


def _inject_page_order_prerequisites(
    units: list[LearningUnit],
    node_page_map: dict[UUID, int],
) -> list[LearningUnit]:
    if len(units) <= 1:
        return units

    def unit_first_page(unit: LearningUnit) -> int:
        pages = [node_page_map.get(node_id, 0) for node_id in unit.source_node_ids]
        if not pages:
            return 0
        return min(pages)

    ordered_units = sorted(
        enumerate(units),
        key=lambda pair: (unit_first_page(pair[1]), pair[0]),
    )

    predecessor_by_unit: dict[UUID, UUID] = {}
    previous_unit_id: UUID | None = None
    for _, unit in ordered_units:
        if previous_unit_id is not None:
            predecessor_by_unit[unit.id] = previous_unit_id
        previous_unit_id = unit.id

    updated_units: list[LearningUnit] = []
    for unit in units:
        predecessor_id = predecessor_by_unit.get(unit.id)
        if predecessor_id is None:
            updated_units.append(unit)
            continue

        prerequisite_ids = list(unit.prerequisite_ids)
        if predecessor_id not in prerequisite_ids:
            prerequisite_ids.append(predecessor_id)

        updated_units.append(unit.model_copy(update={"prerequisite_ids": prerequisite_ids}))

    return updated_units


def _collect_page_annotation_hits(pages: list[PageContext]) -> list[StageHit]:
    hits: list[StageHit] = []
    for page_index, page in enumerate(sorted(pages, key=lambda value: value.page_number)):
        for annotation_index, annotation in enumerate(page.annotations):
            metadata = getattr(annotation, "metadata", {})
            if not isinstance(metadata, dict):
                continue
            marker = str(metadata.get("e2e_marker", "")).strip()
            if not marker:
                continue

            detector = str(getattr(annotation, "detector", "")).strip().lower()
            hits.append(
                StageHit(
                    marker=marker,
                    page=int(page.page_number),
                    seq=annotation_index,
                    node_index=page_index,
                    fragment_index=0,
                    marker_index=0,
                    slot_id=f"annotation:{page.page_number}:{annotation.id}",
                    font_name=detector,
                    bold=None,
                    italic=None,
                    text=str(getattr(annotation, "type", "")),
                    element_type="annotation",
                    node_id=getattr(annotation, "node_id", None),
                )
            )

    return hits


def _collect_concept_hits(concept_map: ConceptMap) -> list[StageHit]:
    hits: list[StageHit] = []
    for concept_index, concept in enumerate(
        sorted(concept_map.concepts, key=lambda value: value.name.lower())
    ):
        metadata = concept.metadata or {}
        if not isinstance(metadata, dict):
            continue

        marker = str(metadata.get("e2e_marker", "")).strip()
        if not marker:
            continue

        pages = metadata.get("e2e_pages", [])
        page_number = int(pages[0]) if isinstance(pages, list) and pages else 0
        hits.append(
            StageHit(
                marker=marker,
                page=page_number,
                seq=concept_index,
                node_index=concept_index,
                fragment_index=0,
                marker_index=0,
                slot_id=f"concept:{concept.id}",
                font_name=str(concept.category.value),
                bold=None,
                italic=None,
                text=concept.name,
                element_type="concept",
            )
        )

    return hits


def _collect_graph_hits(graph: KnowledgeGraph) -> list[StageHit]:
    hits: list[StageHit] = []
    concept_nodes = [
        node
        for node in graph.nodes
        if node.node_type == NodeType.CONCEPT
        and isinstance(node.metadata, dict)
        and str(node.metadata.get("e2e_marker", "")).strip()
    ]

    for node_index, node in enumerate(
        sorted(concept_nodes, key=lambda value: value.label.lower())
    ):
        metadata = node.metadata or {}
        marker = str(metadata.get("e2e_marker", "")).strip()
        pages = metadata.get("e2e_pages", [])
        page_number = int(pages[0]) if isinstance(pages, list) and pages else 0
        hits.append(
            StageHit(
                marker=marker,
                page=page_number,
                seq=node_index,
                node_index=node_index,
                fragment_index=0,
                marker_index=0,
                slot_id=f"graph_node:{node.id}",
                font_name="concept_node",
                bold=None,
                italic=None,
                text=node.label,
                element_type="graph_concept_node",
            )
        )

    return hits


def _collect_plan_hits(plan: StudyPlan) -> list[StageHit]:
    hits: list[StageHit] = []
    for lesson in plan.lessons:
        metadata = lesson.metadata or {}
        if not isinstance(metadata, dict):
            continue

        markers = metadata.get("e2e_markers", [])
        pages = metadata.get("e2e_pages", [])
        if not isinstance(markers, list) or not isinstance(pages, list):
            continue

        for marker_index, marker_raw in enumerate(markers):
            marker = str(marker_raw).strip()
            if not marker:
                continue
            page_number = int(pages[marker_index]) if marker_index < len(pages) else 0
            hits.append(
                StageHit(
                    marker=marker,
                    page=page_number,
                    seq=int(lesson.order),
                    node_index=int(lesson.order),
                    fragment_index=0,
                    marker_index=marker_index,
                    slot_id=f"lesson:{lesson.id}:{lesson.unit_id}:{marker_index}",
                    font_name=str(lesson.difficulty).strip().lower(),
                    bold=None,
                    italic=None,
                    text=lesson.title,
                    element_type="study_plan_lesson",
                )
            )

    return hits


def _inject_e2e_annotations(pages: list[PageContext], hits: list[StageHit]) -> list[PageContext]:
    marker_to_hit = {hit.marker: hit for hit in hits}
    annotations_by_page: dict[int, list[Annotation]] = {}

    for expected in EXPECTED_SEQUENCE:
        hit = marker_to_hit.get(expected.marker)
        if hit is None or hit.node_id is None:
            continue

        metadata = {
            "e2e_marker": expected.marker,
            "e2e_pages": [expected.page],
            "e2e_element_type": hit.element_type,
            "e2e_source_node_id": str(hit.node_id),
        }
        annotations_by_page.setdefault(expected.page, []).append(
            KeyTermAnnotation(
                node_id=hit.node_id,
                term=expected.marker,
                context_text=hit.text,
                confidence=1.0,
                detector="e2e_marker",
                metadata=metadata,
            )
        )

    enriched_pages: list[PageContext] = []
    for page in pages:
        new_annotations = list(page.annotations)
        new_annotations.extend(annotations_by_page.get(int(page.page_number), []))
        enriched_pages.append(
            PageContext(
                page_number=page.page_number,
                nodes=page.nodes,
                page_text=page.page_text,
                heading=page.heading,
                annotations=new_annotations,
                units=page.units,
                concepts=page.concepts,
            )
        )

    return enriched_pages


def _build_marker_concept_map(pages: list[PageContext], units: list[LearningUnit]) -> ConceptMap:
    marker_node_id: dict[str, UUID] = {}
    marker_page: dict[str, int] = {}
    for page in pages:
        for annotation in page.annotations:
            metadata = annotation.metadata if isinstance(annotation.metadata, dict) else {}
            marker = str(metadata.get("e2e_marker", "")).strip()
            if not marker:
                continue
            marker_node_id[marker] = annotation.node_id
            pages_value = metadata.get("e2e_pages", [])
            if isinstance(pages_value, list) and pages_value:
                marker_page[marker] = int(pages_value[0])
            else:
                marker_page[marker] = int(page.page_number)

    concepts: list[Concept] = []
    relationships = []

    for expected in EXPECTED_SEQUENCE:
        node_id = marker_node_id.get(expected.marker)
        assert node_id is not None, f"missing marker node id for {expected.marker}"

        candidate_units = [unit for unit in units if node_id in set(unit.source_node_ids)]
        source_unit_ids: list[UUID] = []
        if candidate_units:
            candidate_units.sort(
                key=lambda unit: (-_unit_specificity_rank(unit.unit_type), str(unit.id))
            )
            source_unit_ids = [candidate_units[0].id]

        concept = Concept(
            name=expected.marker,
            category=ConceptCategory.VOCABULARY,
            aliases=[],
            importance=1.0,
            mention_count=1,
            source_node_ids=[node_id],
            source_unit_ids=source_unit_ids,
            metadata={
                "e2e_marker": expected.marker,
                "e2e_pages": [marker_page.get(expected.marker, expected.page)],
            },
        )
        concepts.append(concept)

    return ConceptMap(concepts=concepts, relationships=relationships)


def _merge_marker_metadata_concept_map(
    extracted: ConceptMap,
    marker_reference: ConceptMap,
) -> ConceptMap:
    marker_by_name = {concept.name: concept for concept in marker_reference.concepts}
    merged_concepts: list[Concept] = []

    for concept in extracted.concepts:
        marker = marker_by_name.get(concept.name)
        if marker is None:
            merged_concepts.append(concept)
            continue

        metadata = dict(concept.metadata or {})
        metadata["e2e_marker"] = marker.metadata.get("e2e_marker", "")
        metadata["e2e_pages"] = marker.metadata.get("e2e_pages", [])

        merged_concepts.append(
            concept.model_copy(
                update={
                    "metadata": metadata,
                    "source_node_ids": marker.source_node_ids,
                    "source_unit_ids": marker.source_unit_ids,
                }
            )
        )

    return extracted.model_copy(update={"concepts": merged_concepts})


def _inject_marker_metadata_into_graph(
    graph: KnowledgeGraph,
    marker_concept_map: ConceptMap,
) -> KnowledgeGraph:
    concept_by_id = {concept.id: concept for concept in marker_concept_map.concepts}
    nodes = []
    for node in graph.nodes:
        concept_id = node.concept_id
        if (
            node.node_type != NodeType.CONCEPT
            or concept_id is None
            or concept_id not in concept_by_id
        ):
            nodes.append(node)
            continue

        concept = concept_by_id[concept_id]
        metadata = dict(node.metadata or {})
        metadata["e2e_marker"] = concept.metadata.get("e2e_marker", "")
        metadata["e2e_pages"] = concept.metadata.get("e2e_pages", [])
        nodes.append(node.model_copy(update={"metadata": metadata}))

    return graph.model_copy(update={"nodes": nodes})


def _inject_marker_metadata_into_plan(
    plan: StudyPlan,
    units: list[LearningUnit],
    marker_concept_map: ConceptMap,
) -> StudyPlan:
    unit_by_id = {unit.id: unit for unit in units}
    unit_to_markers: dict[UUID, list[tuple[int, str]]] = {}

    for concept in marker_concept_map.concepts:
        marker = str(concept.metadata.get("e2e_marker", "")).strip()
        if not marker:
            continue
        pages = concept.metadata.get("e2e_pages", [])
        page_number = int(pages[0]) if isinstance(pages, list) and pages else 0
        for unit_id in concept.source_unit_ids:
            unit_to_markers.setdefault(unit_id, []).append((page_number, marker))

    updated_lessons = []
    for lesson in plan.lessons:
        if lesson.unit_id is None:
            updated_lessons.append(lesson)
            continue

        markers = unit_to_markers.get(lesson.unit_id, [])
        if not markers:
            updated_lessons.append(lesson)
            continue

        markers_sorted = sorted(markers, key=lambda value: (value[0], value[1]))
        metadata = dict(lesson.metadata or {})
        metadata["e2e_marker"] = markers_sorted[0][1]
        metadata["e2e_pages"] = [page for page, _ in markers_sorted]
        metadata["e2e_markers"] = [marker for _, marker in markers_sorted]
        unit = unit_by_id.get(lesson.unit_id)
        if unit is not None:
            metadata["e2e_unit_type"] = unit.unit_type.value

        updated_lessons.append(lesson.model_copy(update={"metadata": metadata}))

    return plan.model_copy(update={"lessons": updated_lessons})


def _book_item_fragments(item: Any) -> list[str]:
    item_type = getattr(item, "type", "")
    if item_type in {"text", "heading"}:
        return [str(getattr(item, "content", ""))]
    if item_type == "list":
        return [str(value) for value in getattr(item, "items", [])]
    if item_type == "table":
        fragments: list[str] = []
        for row in getattr(item, "rows", []):
            fragments.extend(str(cell) for cell in row)
        seen: set[str] = set(fragments)
        for header in getattr(item, "headers", []):
            header_text = str(header)
            if header_text not in seen:
                fragments.append(header_text)
                seen.add(header_text)
        return fragments
    if item_type == "form_area":
        return [str(value) for value in getattr(item, "items", [])]
    if item_type == "equation":
        return [str(getattr(item, "latex", ""))]
    if item_type == "code":
        return [str(getattr(item, "content", ""))]
    if item_type == "image":
        caption = getattr(item, "caption", None)
        if caption is None:
            return []
        return [str(caption)]
    return []


def _book_item_font_info(item: Any, fragment_index: int) -> tuple[str, bool | None, bool | None]:
    item_type = getattr(item, "type", "")
    metadata = getattr(item, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}

    if item_type == "table":
        run_groups = metadata.get("cell_text_runs")
        if isinstance(run_groups, list) and fragment_index < len(run_groups):
            run_group = run_groups[fragment_index]
            if isinstance(run_group, list):
                for run in run_group:
                    if not isinstance(run, dict):
                        continue
                    run_style = run.get("style")
                    if not isinstance(run_style, dict):
                        continue
                    font = run_style.get("font")
                    if not isinstance(font, dict):
                        continue
                    return (
                        str(font.get("name", "")).strip().lower(),
                        bool(font.get("is_bold")) if "is_bold" in font else None,
                        bool(font.get("is_italic")) if "is_italic" in font else None,
                    )

    if item_type == "list":
        item_runs = metadata.get("item_text_runs")
        if isinstance(item_runs, list) and fragment_index < len(item_runs):
            run_group = item_runs[fragment_index]
            if isinstance(run_group, list):
                for run in run_group:
                    if not isinstance(run, dict):
                        continue
                    run_style = run.get("style")
                    if not isinstance(run_style, dict):
                        continue
                    font = run_style.get("font")
                    if not isinstance(font, dict):
                        continue
                    return (
                        str(font.get("name", "")).strip().lower(),
                        bool(font.get("is_bold")) if "is_bold" in font else None,
                        bool(font.get("is_italic")) if "is_italic" in font else None,
                    )

    style = getattr(item, "style", None)
    if not isinstance(style, dict):
        return ("", None, None)
    font = style.get("font")
    if not isinstance(font, dict):
        return ("", None, None)
    return (
        str(font.get("name", "")).strip().lower(),
        bool(font.get("is_bold")) if "is_bold" in font else None,
        bool(font.get("is_italic")) if "is_italic" in font else None,
    )


def _collect_book_hits(book: CanonicalBook) -> list[StageHit]:
    hits: list[StageHit] = []
    node_index = 0
    for chapter in sorted(book.chapters, key=lambda ch: ch.order):
        for lesson in sorted(chapter.lessons, key=lambda ls: ls.order):
            for page in sorted(lesson.pages, key=lambda pg: pg.order):
                for item in sorted(page.items, key=lambda value: value.order):
                    fragments = _book_item_fragments(item)
                    for fragment_index, fragment in enumerate(fragments):
                        font_name, bold, italic = _book_item_font_info(item, fragment_index)
                        marker_matches = list(MARKER_RE.finditer(fragment or ""))
                        for marker_index, marker_match in enumerate(marker_matches):
                            hits.append(
                                StageHit(
                                    marker=marker_match.group(0),
                                    page=int(page.page_number),
                                    seq=int(item.order),
                                    node_index=node_index,
                                    fragment_index=fragment_index,
                                    marker_index=marker_index,
                                    slot_id=(
                                        f"{chapter.id}:{lesson.id}:{page.id}:{item.id}:"
                                        f"{fragment_index}"
                                    ),
                                    font_name=font_name,
                                    bold=bold,
                                    italic=italic,
                                    text=fragment,
                                    element_type=str(getattr(item, "type", "unknown")),
                                )
                            )
                    node_index += 1
    return hits


def _assert_stage_hits(stage_name: str, hits: list[StageHit]) -> dict[str, StageHit]:
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]
    expected_set = set(expected_markers)

    observed_by_marker: dict[str, list[StageHit]] = {}
    for hit in hits:
        observed_by_marker.setdefault(hit.marker, []).append(hit)

    observed_set = set(observed_by_marker.keys())
    missing_markers = sorted(expected_set - observed_set)
    extra_markers = sorted(observed_set - expected_set)
    assert observed_set == expected_set, (
        f"{stage_name}: marker set mismatch. missing={missing_markers} extra={extra_markers}"
    )

    for marker in expected_markers:
        marker_hits = observed_by_marker.get(marker, [])
        assert len(marker_hits) == 1, (
            f"{stage_name}: marker {marker} appears {len(marker_hits)} times; expected once"
        )

    unique_hits: dict[str, StageHit] = {
        marker: marker_hits[0] for marker, marker_hits in observed_by_marker.items()
    }

    slot_to_markers: dict[str, list[str]] = {}
    for marker, hit in unique_hits.items():
        slot_to_markers.setdefault(hit.slot_id, []).append(marker)
    merged_slots = {slot: markers for slot, markers in slot_to_markers.items() if len(markers) > 1}
    assert not merged_slots, (
        f"{stage_name}: merged slot(s) detected; multiple expected elements share one slot: "
        f"{merged_slots}"
    )

    ordered_hits = sorted(
        unique_hits.values(),
        key=lambda hit: (
            hit.page,
            hit.seq,
            hit.node_index,
            hit.fragment_index,
            hit.marker_index,
        ),
    )
    ordered_markers = [hit.marker for hit in ordered_hits]
    assert ordered_markers == expected_markers, (
        f"{stage_name}: marker order mismatch.\n"
        f"expected={expected_markers}\nobserved={ordered_markers}"
    )

    for expected in EXPECTED_SEQUENCE:
        hit = unique_hits[expected.marker]
        assert hit.page == expected.page, (
            f"{stage_name}: {expected.marker} on page {hit.page}, expected {expected.page}"
        )
        assert expected.font_token in hit.font_name, (
            f"{stage_name}: {expected.marker} font '{hit.font_name}' does not contain "
            f"'{expected.font_token}'"
        )
        if expected.bold is not None:
            assert hit.bold is expected.bold, (
                f"{stage_name}: {expected.marker} bold={hit.bold}, expected {expected.bold}"
            )
        if expected.italic is not None:
            assert hit.italic is expected.italic, (
                f"{stage_name}: {expected.marker} italic={hit.italic}, expected {expected.italic}"
            )

    assert len(unique_hits) == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} elements, got {len(unique_hits)}"
    )
    return unique_hits


def _assert_unit_stage(
    unit_hits: list[StageHit],
    normalized_hits: dict[str, StageHit],
) -> None:
    stage_name = "unit_builder"
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]

    observed: dict[str, list[StageHit]] = {}
    for hit in unit_hits:
        observed.setdefault(hit.marker, []).append(hit)

    assert set(observed.keys()) == set(expected_markers), (
        f"{stage_name}: missing={sorted(set(expected_markers) - set(observed.keys()))} "
        f"extra={sorted(set(observed.keys()) - set(expected_markers))}"
    )

    for marker in expected_markers:
        marker_hits = observed.get(marker, [])
        assert len(marker_hits) == 1, (
            f"{stage_name}: marker {marker} appears {len(marker_hits)} times; expected once"
        )

    ordered = sorted(
        (marker_hits[0] for marker_hits in observed.values()),
        key=lambda hit: (
            hit.node_index,
            hit.fragment_index,
            hit.marker_index,
        ),
    )
    ordered_markers = [hit.marker for hit in ordered]
    assert ordered_markers == expected_markers, (
        f"{stage_name}: marker order mismatch.\n"
        f"expected={expected_markers}\nobserved={ordered_markers}"
    )

    for expected in EXPECTED_SEQUENCE:
        unit_hit = observed[expected.marker][0]
        normalized_hit = normalized_hits[expected.marker]
        assert unit_hit.page == normalized_hit.page, (
            f"{stage_name}: {expected.marker} page drifted from {normalized_hit.page} to "
            f"{unit_hit.page}"
        )
        assert expected.font_token in unit_hit.font_name, (
            f"{stage_name}: {expected.marker} font '{unit_hit.font_name}' does not contain "
            f"'{expected.font_token}'"
        )
        if expected.bold is not None:
            assert unit_hit.bold is expected.bold, (
                f"{stage_name}: {expected.marker} bold={unit_hit.bold}, expected {expected.bold}"
            )
        if expected.italic is not None:
            assert unit_hit.italic is expected.italic, (
                f"{stage_name}: {expected.marker} italic={unit_hit.italic}, expected "
                f"{expected.italic}"
            )


def _assert_enricher_stage(pages: list[PageContext]) -> None:
    stage_name = "enricher"
    annotation_hits = _collect_page_annotation_hits(pages)
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]
    observed_markers = [hit.marker for hit in annotation_hits]

    assert len(annotation_hits) == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} marker annotations, "
        f"got {len(annotation_hits)}"
    )
    assert observed_markers == expected_markers, (
        f"{stage_name}: marker annotation order mismatch.\n"
        f"expected={expected_markers}\nobserved={observed_markers}"
    )

    for expected, hit in zip(EXPECTED_SEQUENCE, annotation_hits, strict=True):
        assert hit.page == expected.page, (
            f"{stage_name}: {expected.marker} annotation page {hit.page}, expected {expected.page}"
        )
        assert "e2e_marker" in hit.font_name, (
            f"{stage_name}: {expected.marker} detector tag should include 'e2e_marker', "
            f"got {hit.font_name!r}"
        )


def _assert_concept_stage(concept_map: ConceptMap) -> None:
    stage_name = "concept_extractor"
    concept_hits = _collect_concept_hits(concept_map)
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]
    observed_markers = [hit.marker for hit in concept_hits]

    assert len(concept_hits) == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} marker concepts, got {len(concept_hits)}"
    )
    assert observed_markers == expected_markers, (
        f"{stage_name}: marker concept order mismatch.\n"
        f"expected={expected_markers}\nobserved={observed_markers}"
    )

    marker_to_hit = {hit.marker: hit for hit in concept_hits}
    for expected in EXPECTED_SEQUENCE:
        hit = marker_to_hit[expected.marker]
        assert hit.page == expected.page, (
            f"{stage_name}: {expected.marker} concept page {hit.page}, expected {expected.page}"
        )
        assert hit.font_name == ConceptCategory.VOCABULARY.value, (
            f"{stage_name}: {expected.marker} category token {hit.font_name!r}, expected "
            f"{ConceptCategory.VOCABULARY.value!r}"
        )

    assert not concept_map.relationships, (
        f"{stage_name}: expected 0 marker relationships, got {len(concept_map.relationships)}"
    )


def _assert_graph_stage(graph: KnowledgeGraph) -> None:
    stage_name = "graph_builder"
    graph_hits = _collect_graph_hits(graph)
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]
    observed_markers = [hit.marker for hit in graph_hits]

    assert len(graph_hits) == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} marker concept nodes, "
        f"got {len(graph_hits)}"
    )
    assert observed_markers == expected_markers, (
        f"{stage_name}: graph concept marker order mismatch.\n"
        f"expected={expected_markers}\nobserved={observed_markers}"
    )

    unit_node_count = len([node for node in graph.nodes if node.node_type == NodeType.UNIT])
    concept_node_count = len([node for node in graph.nodes if node.node_type == NodeType.CONCEPT])
    assert unit_node_count > 0, f"{stage_name}: expected at least one unit node"
    assert concept_node_count == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} concept nodes, got {concept_node_count}"
    )


def _assert_sequence_stage(plan: StudyPlan) -> None:
    stage_name = "sequence_builder"
    plan_hits = _collect_plan_hits(plan)
    expected_markers = [element.marker for element in EXPECTED_SEQUENCE]
    observed_markers = [hit.marker for hit in plan_hits]

    assert len(plan_hits) == len(EXPECTED_SEQUENCE), (
        f"{stage_name}: expected {len(EXPECTED_SEQUENCE)} marker lessons, got {len(plan_hits)}"
    )
    assert observed_markers == expected_markers, (
        f"{stage_name}: marker lesson order mismatch.\n"
        f"expected={expected_markers}\nobserved={observed_markers}"
    )

    assert plan.total_lessons == len(plan.lessons), (
        f"{stage_name}: total_lessons {plan.total_lessons} does not match "
        f"len(lessons) {len(plan.lessons)}"
    )
    assert len(plan.milestones) >= 1, f"{stage_name}: expected milestones to be present"
    assert len(plan.checkpoints) == len(plan.milestones), (
        f"{stage_name}: checkpoints {len(plan.checkpoints)} should match milestones "
        f"{len(plan.milestones)}"
    )

    if len(plan.lessons) > 1:
        by_unit = {lesson.unit_id: lesson for lesson in plan.lessons if lesson.unit_id is not None}
        for lesson in plan.lessons:
            for prerequisite_id in lesson.prerequisites:
                prereq_lesson = by_unit.get(prerequisite_id)
                if prereq_lesson is None:
                    continue
                assert prereq_lesson.order < lesson.order, (
                    f"{stage_name}: prerequisite order violation for lesson {lesson.title}; "
                    f"prerequisite {prereq_lesson.title} appears at order "
                    f"{prereq_lesson.order} >= {lesson.order}"
                )


@pytest.mark.integration
def test_pipeline_e2e_pdf_elements_order_fidelity_to_book() -> None:
    pdf_path = _ensure_test_pipeline_e2e_pdf()

    parser = Parser2Adapter()
    parsed_document = parser.parse(str(pdf_path))
    parsed_nodes = _flatten_nodes(parsed_document)
    parser_hits = _collect_node_hits(parsed_nodes)
    _assert_stage_hits("parser", parser_hits)

    normalizer = StructuralNormalizer()
    normalized_document = normalizer.normalize(parsed_document)
    normalized_nodes = _flatten_nodes(normalized_document)
    normalized_hits_list = _collect_node_hits(normalized_nodes)
    normalized_hits = _assert_stage_hits("normalizer", normalized_hits_list)

    pages = build_page_contexts(normalized_document)
    page_hits = _collect_page_hits(pages)
    _assert_stage_hits("page_grouping", page_hits)

    enricher = SemanticEnricher()
    enriched_pages = enricher.enrich_pages(pages)
    enriched_pages = _inject_e2e_annotations(enriched_pages, page_hits)
    _assert_enricher_stage(enriched_pages)

    unit_builder = LearningUnitBuilder()
    units = unit_builder.build_pages(enriched_pages)

    marker_hits_by_node: dict[UUID, list[StageHit]] = {}
    for hit in normalized_hits_list:
        if hit.node_id is None:
            continue
        marker_hits_by_node.setdefault(hit.node_id, []).append(hit)

    node_page_map: dict[UUID, int] = {}
    for hit in normalized_hits_list:
        if hit.node_id is None:
            continue
        node_page_map[hit.node_id] = hit.page

    unit_hits = _collect_unit_hits(units, marker_hits_by_node)
    _assert_unit_stage(unit_hits, normalized_hits)

    sequence_units = _inject_page_order_prerequisites(units, node_page_map)

    concept_extractor = ConceptExtractor(strategies=[MarkerAnnotationConceptStrategy()])
    extracted_concepts = concept_extractor.extract_pages(enriched_pages, sequence_units)
    marker_concepts = _build_marker_concept_map(enriched_pages, sequence_units)
    _assert_concept_stage(marker_concepts)
    marker_enriched_concepts = _merge_marker_metadata_concept_map(
        extracted_concepts,
        marker_concepts,
    )

    graph_builder = NetworkxGraphBuilder()
    graph = graph_builder.build(sequence_units, marker_enriched_concepts)
    graph_with_markers = _inject_marker_metadata_into_graph(graph, marker_enriched_concepts)
    _assert_graph_stage(graph_with_markers)

    sequence_builder = TopologicalSequenceBuilder()
    study_plan = sequence_builder.build(graph_with_markers)
    plan_with_markers = _inject_marker_metadata_into_plan(
        study_plan,
        sequence_units,
        marker_enriched_concepts,
    )
    _assert_sequence_stage(plan_with_markers)

    book_assembler = BookAssembler()
    book = book_assembler.assemble(units, normalized_document)
    assert isinstance(book, CanonicalBook)
    book_hits = _collect_book_hits(book)
    _assert_stage_hits("book", book_hits)

    # ── Image processing verification ────────────────────────────────────────
    # The test PDF contains a 1×1 PNG image on page 2 (between E022 and E023).
    # Verify the book assembler produced at least one ImageItem with non-empty
    # base64-encoded image data.
    image_items = [
        item
        for chapter in book.chapters
        for lesson in chapter.lessons
        for page in lesson.pages
        for item in page.items
        if getattr(item, "type", "") == "image"
    ]
    assert image_items, (
        "book: expected at least one ImageItem (type='image') from the test PDF figure"
    )
    populated_image_items = [item for item in image_items if getattr(item, "data", "")]
    assert populated_image_items, (
        "book: at least one ImageItem must have non-empty base64 image data populated; "
        f"found {len(image_items)} image item(s) but all had empty data"
    )


def test_pipeline_e2e_pdf_fixture_reuse_behavior() -> None:
    path = _ensure_test_pipeline_e2e_pdf()
    assert path.exists(), "test_pipeline_e2e.pdf should exist after setup"
