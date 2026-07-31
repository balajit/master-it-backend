import fitz  # PyMuPDF
import json
import os
from pathlib import Path
from typing import List, Dict, Any, Optional

# Docling Imports
from docling.document_converter import DocumentConverter

# Import Pydantic Schemas
from schema import (
    CanonicalDocument,
    LearningUnit,
    PageDimensions,
    DocumentElement,
    BoundingBox,
    TextStyle,
    FontSpec,
    ImageMetadata,
    TableMetadata,
    EquationMetadata
)


def calculate_overlap(bbox1: BoundingBox, bbox2: BoundingBox) -> float:
    """Calculates the ratio of bbox1's area that overlaps with bbox2."""
    inter_l = max(bbox1.l, bbox2.l)
    inter_t = max(bbox1.t, bbox2.t)
    inter_r = min(bbox1.r, bbox2.r)
    inter_b = min(bbox1.b, bbox2.b)

    if inter_r <= inter_l or inter_b <= inter_t:
        return 0.0

    inter_area = (inter_r - inter_l) * (inter_b - inter_t)
    bbox1_area = (bbox1.r - bbox1.l) * (bbox1.b - bbox1.t)

    if bbox1_area <= 0:
        return 0.0

    return inter_area / bbox1_area


def extract_docling_semantic_blocks(pdf_path: str) -> Dict[int, List[Dict[str, Any]]]:
    """Runs Docling and extracts page-wise semantic items including Tables and Formulas."""
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    doc = result.document

    pages_semantics: Dict[int, List[Dict[str, Any]]] = {}

    # 1. Text & Math Items (Headings, Paragraphs, Code, Formulas)
    for text_item in doc.texts:
        label = text_item.label.value if hasattr(text_item.label, "value") else str(text_item.label)

        # Check for LaTeX formula properties if provided by Docling
        latex_str = getattr(text_item, "text", None) if label in ["FORMULA", "EQUATION"] else None

        for prov in text_item.prov:
            page_no = prov.page_no
            pages_semantics.setdefault(page_no, []).append({
                "label": label,
                "text": text_item.text,
                "latex": latex_str,
                "parent_ref": text_item.parent.cref if text_item.parent else None,
                "bbox": BoundingBox(
                    l=round(prov.bbox.l, 2),
                    t=round(prov.bbox.t, 2),
                    r=round(prov.bbox.r, 2),
                    b=round(prov.bbox.b, 2)
                )
            })

    # 2. Table Items with Structure Export
    for table_item in doc.tables:
        df = table_item.export_to_dataframe()
        csv_repr = df.to_csv(index=False) if df is not None else None
        html_repr = table_item.export_to_html() if hasattr(table_item, "export_to_html") else None

        for prov in table_item.prov:
            page_no = prov.page_no
            pages_semantics.setdefault(page_no, []).append({
                "label": "TABLE",
                "text": "[TABLE DATA]",
                "parent_ref": table_item.parent.cref if table_item.parent else None,
                "table_meta": TableMetadata(
                    num_rows=table_item.data.num_rows if hasattr(table_item, "data") else len(df),
                    num_cols=table_item.data.num_cols if hasattr(table_item, "data") else len(df.columns),
                    csv_repr=csv_repr,
                    html_repr=html_repr
                ),
                "bbox": BoundingBox(
                    l=round(prov.bbox.l, 2),
                    t=round(prov.bbox.t, 2),
                    r=round(prov.bbox.r, 2),
                    b=round(prov.bbox.b, 2)
                )
            })

    return pages_semantics


def build_semantic_canonical_document(pdf_path: str, output_assets_dir: str = "extracted_assets") -> CanonicalDocument:
    os.makedirs(output_assets_dir, exist_ok=True)

    print("1. Extracting AI Semantic Blocks, Tables & Equations with Docling...")
    docling_blocks_by_page = extract_docling_semantic_blocks(pdf_path)

    print("2. Extracting Fine-Grained Typography & Assets with PyMuPDF...")
    fitz_doc = fitz.open(pdf_path)

    canonical_doc = CanonicalDocument(
        document_id=Path(pdf_path).stem,
        filename=os.path.basename(pdf_path),
        total_pages=len(fitz_doc),
        learning_units=[]
    )

    for page_idx in range(len(fitz_doc)):
        page_num = page_idx + 1
        page = fitz_doc[page_idx]
        page_rect = page.rect

        docling_page_blocks = docling_blocks_by_page.get(page_num, [])

        unit = LearningUnit(
            unit_id=f"unit_page_{page_num}",
            page_number=page_num,
            page_dimensions=PageDimensions(
                width=page_rect.width,
                height=page_rect.height,
                unit="pt"
            ),
            typography_manifest={},
            elements=[]
        )

        page_text_data = page.get_text("rawdict")
        font_catalog: Dict[str, FontSpec] = {}
        element_counter = 0

        # --- Extract Text, Formulas & Code Spans ---
        for block in page_text_data.get("blocks", []):
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        element_counter += 1

                        font_name = span.get("font", "Unknown")
                        font_size = round(span.get("size", 0), 2)
                        font_color = f"#{span.get('color', 0):06x}"
                        font_id = f"font_{hash(font_name + str(font_size) + font_color) % 10000}"

                        if font_id not in font_catalog:
                            font_catalog[font_id] = FontSpec(
                                font_name=font_name,
                                size=font_size,
                                color=font_color
                            )

                        span_bbox = BoundingBox(
                            l=round(span["bbox"][0], 2),
                            t=round(span["bbox"][1], 2),
                            r=round(span["bbox"][2], 2),
                            b=round(span["bbox"][3], 2)
                        )

                        # Spatial matching with Docling blocks
                        assigned_label = "PARAGRAPH"
                        parent_ref = None
                        matched_d_block = None
                        best_overlap = 0.0

                        for d_block in docling_page_blocks:
                            overlap = calculate_overlap(span_bbox, d_block["bbox"])
                            if overlap > 0.5 and overlap > best_overlap:
                                best_overlap = overlap
                                assigned_label = d_block["label"]
                                parent_ref = d_block["parent_ref"]
                                matched_d_block = d_block

                        # Classify Element Type
                        elem_type = "text_span"
                        eq_metadata = None
                        table_metadata = None

                        if assigned_label in ["FORMULA", "EQUATION"]:
                            elem_type = "formula"
                            eq_metadata = EquationMetadata(
                                latex_repr=matched_d_block.get("latex") if matched_d_block else span.get("text"),
                                is_inline=bool(span_bbox.r - span_bbox.l < page_rect.width * 0.5)
                            )
                        elif assigned_label == "CODE":
                            elem_type = "code_block"
                        elif assigned_label == "TABLE" and matched_d_block:
                            elem_type = "table"
                            table_metadata = matched_d_block.get("table_meta")

                        unit.elements.append(DocumentElement(
                            element_id=f"p{page_num}_e{element_counter}",
                            type=elem_type,
                            label=assigned_label,
                            parent_hierarchy_ref=parent_ref,
                            text=span.get("text"),
                            bbox=span_bbox,
                            style=TextStyle(
                                font_id=font_id,
                                is_bold=bool(span.get("flags", 0) & 2 ** 4),
                                is_italic=bool(span.get("flags", 0) & 2 ** 1),
                                is_monospace=bool(span.get("flags", 0) & 2 ** 3)
                            ),
                            equation_metadata=eq_metadata,
                            table_metadata=table_metadata
                        ))

        # --- Extract Images ---
        for img_idx, img_info in enumerate(page.get_images(full=True)):
            xref = img_info[0]
            base_image = fitz_doc.extract_image(xref)
            image_filename = f"page_{page_num}_img_{img_idx + 1}.{base_image['ext']}"
            image_path = os.path.join(output_assets_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(base_image["image"])

            for img_rect in page.get_image_rects(xref):
                element_counter += 1
                unit.elements.append(DocumentElement(
                    element_id=f"p{page_num}_e{element_counter}",
                    type="image",
                    label="PICTURE",
                    bbox=BoundingBox(
                        l=round(img_rect.x0, 2),
                        t=round(img_rect.y0, 2),
                        r=round(img_rect.x1, 2),
                        b=round(img_rect.y1, 2)
                    ),
                    image_metadata=ImageMetadata(
                        pixel_width=base_image["width"],
                        pixel_height=base_image["height"],
                        rendered_width_pt=round(img_rect.width, 2),
                        rendered_height_pt=round(img_rect.height, 2),
                        format=base_image["ext"],
                        asset_path=image_path
                    )
                ))

        unit.typography_manifest = font_catalog
        canonical_doc.learning_units.append(unit)

    return canonical_doc


# --- Execution Example ---
if __name__ == "__main__":
    canonical_obj: CanonicalDocument = build_semantic_canonical_document("stem_textbook.pdf")

    # Serialize to JSON
    with open("canonical_document.json", "w", encoding="utf-8") as f:
        f.write(canonical_obj.model_dump_json(indent=2))

    print("Complete! Extracted Text, Formulas, Tables, Code, and Images into Pydantic Canonical Model.")