from uuid import UUID

from learning_platform.stages.enricher.semantic import SemanticEnricher
from learning_platform.stages.parser2 import Parser2Adapter
from learning_platform.stages.normalizer.structural import StructuralNormalizer
from learning_platform.models.page_context import build_page_contexts
from learning_platform.stages.unit_builder.builder import LearningUnitBuilder
from learning_platform.models.document import Heading

from test_pipeline_e2e_book_order import (
    _ensure_test_pipeline_e2e_pdf,
    _flatten_nodes,
    _node_fragments,
    _collect_node_hits,
    _test_pdf_path,
    MARKER_RE,
)

pdf_path = _ensure_test_pipeline_e2e_pdf()
parser = Parser2Adapter()

from learning_platform.stages.parser2.docling_pymupdf_merger import DoclingPyMuPDFMerger

with DoclingPyMuPDFMerger(str(pdf_path)) as merger:
    bridge = merger.build_bridge_tree()


def walk_bridge(node, depth=0):
    if node.page_no in (1, 2) and depth <= 3:
        print(
            f"bridge p{node.page_no} d{depth} col={node.column_no} top={node.norm_top:.3f} "
            f"left={node.norm_left:.3f} right={node.norm_right:.3f} "
            f"{node.label!r} name={node.name!r} text={node.text!r}"
        )
    for child in node.children:
        walk_bridge(child, depth + 1)


walk_bridge(bridge.root)

print("=== DOCLING ITEMS page 2 ===")
try:
    items = merger.docling_doc.iterate_items(with_groups=True)
except TypeError:
    items = merger.docling_doc.iterate_items()
for item, level in items:
    page_no = 0
    if getattr(item, "prov", None):
        page_no = item.prov[0].page_no
    print(
        f"  d{level} {type(item).__name__} label={item.label} ref={getattr(item, 'self_ref', None)!r} text={getattr(item, 'text', '')!r} page={page_no}"
    )


def find_table_cell_nodes(node):
    for child in node.children:
        if child.label == "AI-TABLE_ROW":
            for cell in child.children:
                yield cell
        yield from find_table_cell_nodes(child)


for cell in find_table_cell_nodes(bridge.root):
    doc_cell = getattr(cell, "docling_item", None)
    prov = getattr(doc_cell, "prov", None) if doc_cell is not None else None
    if cell.metadata.get("table_row_index") == 0 and cell.metadata.get("table_col_index") == 0:
        print("RAW prov page1:", prov)
        if doc_cell is not None:
            attrs = [a for a in dir(doc_cell) if not a.startswith("__")]
            print("CELL attrs:", attrs)
            for attr in ("bbox", "bbox_asr", "bbox_ocr", "origin_bbox"):
                try:
                    print(f"  {attr} =", getattr(doc_cell, attr))
                except Exception as exc:
                    print(f"  {attr} err:", exc)
    if (
        cell.metadata.get("table_row_index") == 0
        and cell.metadata.get("table_col_index") == 0
        and cell.page_no == 3
    ):
        print("RAW prov page3:", prov)

for cell in find_table_cell_nodes(bridge.root):
    if (
        cell.page_no == 1
        and cell.metadata.get("table_col_index") == 0
        and cell.metadata.get("table_row_index") == 0
    ):
        print(
            "DEBUG header cell text",
            repr(cell.text),
            "bbox",
            cell.norm_left,
            cell.norm_top,
            cell.norm_right,
            cell.norm_bottom,
        )
        cache = merger.page_style_caches.get(1)
        import fitz

        rect = fitz.Rect(
            cell.norm_left * cache.page_w,
            cell.norm_top * cache.page_h,
            cell.norm_right * cache.page_w,
            cell.norm_bottom * cache.page_h,
        )
        search = rect + (-3, -3, 3, 3)
        for span_rect, span in cache.spans:
            inter = search & span_rect
            if inter.is_empty:
                continue
            print("   span", repr(span.get("text")), "font", span.get("font"), "rect", span_rect)
        style = cache.query_style(
            norm_left=cell.norm_left,
            norm_top=cell.norm_top,
            norm_right=cell.norm_right,
            norm_bottom=cell.norm_bottom,
            node_text=cell.text,
        )
        print("   QUERY RESULT", style["font_name"], style["is_bold"], style["fitz_text"])

parsed = parser.parse(str(pdf_path))
from learning_platform.models.document import TableBlock

for n in _flatten_nodes(parsed):
    if isinstance(n.content, TableBlock):
        for row in n.content.rows:
            for cell in row.cells:
                text = "".join(r.text for r in cell.content)
                run = cell.content[0] if cell.content else None
                style = getattr(run, "style", None)
                font = getattr(style, "font", None)
                print(
                    f"cell {row.metadata.get('table_row_index')},{cell.metadata.get('table_col_index')} "
                    f"text={text!r} font={getattr(font, 'name', None)} "
                    f"bold={getattr(font, 'is_bold', None)} header={cell.header}"
                )
parsed_nodes = _flatten_nodes(parsed)

print("=== PARSER STAGE: node -> markers ===")
for n in parsed_nodes:
    frags = _node_fragments(n)
    markers = [m for f in frags for m in MARKER_RE.findall(f or "")]
    if markers:
        kind = type(n.content).__name__
        print(f"{n.seq} {kind} page={n.page} -> {markers}")

print("=== PARSER STAGE page2 all node kinds ===")
for n in parsed_nodes:
    if n.page == 2:
        print(
            f"{n.seq} {type(n.content).__name__} has_image={getattr(n.content, 'image_base64', '') != ''} bbox={n.bbox is not None}"
        )

normalizer = StructuralNormalizer()
normalized = normalizer.normalize(parsed)
pages = build_page_contexts(normalized)
normalized_hits_list = _collect_node_hits(_flatten_nodes(normalized))

hits_by_node: dict[UUID, list] = {}
for hit in normalized_hits_list:
    if hit.node_id is None:
        continue
    hits_by_node.setdefault(hit.node_id, []).append(hit)

print("=== NORMALIZED PAGE 1 node order ===")
for page in sorted(pages, key=lambda p: p.page_number):
    if page.page_number != 1:
        continue
    for i, node in enumerate(page.nodes):
        frags = _node_fragments(node)
        markers = [m for f in frags for m in MARKER_RE.findall(f or "")]
        kind = type(node.content).__name__
        print(f"p1[{i}] {kind} seq={node.seq} markers={markers}")

enricher = SemanticEnricher()
enriched = enricher.enrich_pages(pages)
units = LearningUnitBuilder().build_pages(enriched)

print("=== UNITS (build_pages order) ===")
for unit_index, unit in enumerate(units):
    markers = []
    for nid in unit.source_node_ids:
        for hit in hits_by_node.get(nid, []):
            markers.append(hit.marker)
    markers.sort()
    print(f"unit[{unit_index}] {unit.unit_type} {unit.title!r} markers={markers}")

_ = _test_pdf_path
