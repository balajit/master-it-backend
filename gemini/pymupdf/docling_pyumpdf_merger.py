import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional
from pydantic import BaseModel
from docling.document_converter import DocumentConverter


# 1. Unified Wrapper Model
class CorrelatedItem:
    """Wraps Docling's semantic item with PyMuPDF's low-level styling and vector primitives."""

    def __init__(self, docling_item: Any, level: int):
        self.docling_item = docling_item
        self.level = level
        self.self_ref = getattr(docling_item, "self_ref", None)
        self.label = getattr(docling_item, "label", type(docling_item).__name__)
        self.text = getattr(docling_item, "text", "").strip()

        # Structural Parent Pointer
        self.parent_cref = (
            docling_item.parent.cref if hasattr(docling_item, "parent") and docling_item.parent else None
        )

        # PyMuPDF Correlated Formatting Data
        self.fonts: List[Dict[str, Any]] = []
        self.primary_font_name: Optional[str] = None
        self.primary_font_size: Optional[float] = None
        self.primary_color_hex: Optional[str] = None
        self.is_bold: bool = False
        self.is_italic: bool = False

        # Vector Answer Lines associated with this item
        self.vector_lines: List[Dict[str, Any]] = []

    def __repr__(self):
        font_info = f" | Font: {self.primary_font_name}, {self.primary_font_size}pt" if self.primary_font_name else ""
        lines_info = f" | Attached Lines: {len(self.vector_lines)}" if self.vector_lines else ""
        return f"<CorrelatedItem [{self.label}] '{self.text[:35]}...' {font_info}{lines_info}>"


# 2. Overlap Scoring Helper (IoU / Overlap Ratio)
def compute_bbox_overlap_ratio(box1: List[float], box2: fitz.Rect) -> float:
    """Calculates how much of box1 (Docling BBox) is covered by box2 (PyMuPDF Rect)."""
    rect1 = fitz.Rect(box1[0], box1[1], box1[2], box1[3])
    intersection = rect1.intersect(box2)

    if intersection.is_empty or rect1.area == 0:
        return 0.0

    return intersection.area / rect1.area


# 3. Main Merger Engine Class
class DoclingPyMuPDFMerger:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

        # Step A: Run Docling Conversion
        print("Running Docling conversion...")
        converter = DocumentConverter()
        docling_result = converter.convert(pdf_path)
        self.docling_doc = docling_result.document

        # Step B: Open PyMuPDF Document
        self.fitz_doc = fitz.open(pdf_path)

    def _extract_pymupdf_page_data(self, page_num: int) -> Dict[str, Any]:
        """Extracts text spans and vector lines from a PyMuPDF page."""
        page = self.fitz_doc[page_num - 1]  # 0-indexed

        # Extract Text Spans with Font Metadata
        spans = []
        raw_dict = page.get_text("rawdict")
        for block in raw_dict.get("blocks", []):
            if block.get("type") == 0:
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        spans.append({
                            "rect": fitz.Rect(span["bbox"]),
                            "text": span.get("text"),
                            "font": span.get("font"),
                            "size": round(span.get("size", 0), 2),
                            "color": f"#{span.get('color', 0):06x}",
                            "is_bold": bool(span.get("flags", 0) & 2**4),
                            "is_italic": bool(span.get("flags", 0) & 2**1),
                        })

        # Extract Vector Drawings (Answer Lines / Rules)
        vector_lines = []
        for path in page.get_drawings():
            for item in path.get("items", []):
                if item[0] == "l":  # Line command
                    p1, p2 = item[1], item[2]
                    if abs(p1.y - p2.y) < 2.0 and abs(p1.x - p2.x) >= 20.0:  # Horizontal line
                        line_rect = fitz.Rect(min(p1.x, p2.x), min(p1.y, p2.y) - 2, max(p1.x, p2.x), max(p1.y, p2.y) + 2)
                        vector_lines.append({
                            "rect": line_rect,
                            "length": round(abs(p1.x - p2.x), 2),
                            "top": line_rect.y0,
                        })

        return {"spans": spans, "vector_lines": vector_lines}

    def correlate(self) -> List[CorrelatedItem]:
        """Iterates over Docling items and merges PyMuPDF typography and vector graphics."""
        correlated_items: List[CorrelatedItem] = []

        # Cache PyMuPDF data per page to avoid redundant extraction
        page_cache = {}

        for doc_item, level in self.docling_doc.iterate_items():
            item_wrapper = CorrelatedItem(doc_item, level)

            # Check if Docling item has provenance/bounding box
            if hasattr(doc_item, "prov") and doc_item.prov:
                prov = doc_item.prov[0]
                page_no = prov.page_no
                docling_bbox = [prov.bbox.l, prov.bbox.t, prov.bbox.r, prov.bbox.b]

                if page_no not in page_cache:
                    page_cache[page_no] = self._extract_pymupdf_page_data(page_no)

                pymupdf_data = page_cache[page_no]

                # --- 1. Correlate Spans (Fonts / Formatting) ---
                matching_spans = []
                for span in pymupdf_data["spans"]:
                    # Overlap ratio check
                    if compute_bbox_overlap_ratio(docling_bbox, span["rect"]) > 0.3:
                        matching_spans.append(span)

                if matching_spans:
                    item_wrapper.fonts = matching_spans
                    # Use the dominant span (first or largest) for primary font properties
                    item_wrapper.primary_font_name = matching_spans[0]["font"]
                    item_wrapper.primary_font_size = matching_spans[0]["size"]
                    item_wrapper.primary_color_hex = matching_spans[0]["color"]
                    item_wrapper.is_bold = any(s["is_bold"] for s in matching_spans)
                    item_wrapper.is_italic = any(s["is_italic"] for s in matching_spans)

                # --- 2. Correlate Vector Lines (Answer lines sitting directly underneath) ---
                item_bottom_y = docling_bbox[3]
                for v_line in pymupdf_data["vector_lines"]:
                    # Line sits directly below this text block (within 15pt margin)
                    if 0 <= (v_line["top"] - item_bottom_y) <= 15.0:
                        # Check horizontal alignment
                        if not (v_line["rect"].x1 < docling_bbox[0] or v_line["rect"].x0 > docling_bbox[2]):
                            item_wrapper.vector_lines.append(v_line)

            correlated_items.append(item_wrapper)

        return correlated_items


# --- Execution Example ---
if __name__ == "__main__":
    merger = DoclingPyMuPDFMerger("pdfs/csg.pdf")
    items = merger.correlate()

    print("\nMerged Correlated Items Output:")
    print("=" * 70)

    for item in items[:15]:  # Print first 15 items
        print(f"[{item.label}] (Level {item.level})")
        print(f"  ├── Text       : {item.text[:50]}...")
        print(f"  ├── Self Ref   : {item.self_ref}")
        print(f"  ├── Font Name  : {item.primary_font_name}")
        print(f"  ├── Font Size  : {item.primary_font_size} pt")
        print(f"  ├── Color Hex  : {item.primary_color_hex}")
        print(f"  ├── Bold/Italic: Bold={item.is_bold}, Italic={item.is_italic}")
        print(f"  └── Answer Lines: {len(item.vector_lines)} detected")
        print("-" * 70)