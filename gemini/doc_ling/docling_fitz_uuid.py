import uuid
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional

# Docling imports for advanced pipeline configuration
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

import fitz
from typing import Dict, Any, List, Optional, Tuple

import base64
import io
import fitz
import uuid
from typing import List, Dict, Any, Optional, Tuple

from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import PdfPipelineOptions
from docling.datamodel.base_models import InputFormat

from PIL import Image

class PageStyleCache:
    """Pre-loads and indexes all PyMuPDF text spans for a page by bounding box and text."""

    def __init__(self, page: fitz.Page):
        self.page_no = page.number + 1
        self.page_w = page.rect.width
        self.page_h = page.rect.height

        # List of indexed span items: (fitz.Rect, span_dict)
        self.spans: List[Tuple[fitz.Rect, Dict[str, Any]]] = []
        self._build_index(page)

    def _build_index(self, page: fitz.Page):
        """Builds a spatially sorted cache of text spans from the page."""
        page_dict = page.get_text("dict")

        for block in page_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span.get("text", "").strip()
                    if not text:
                        continue  # Skip empty padding

                    bbox = fitz.Rect(span["bbox"])
                    self.spans.append((bbox, span))

        # Sort spatially: Page Top-to-Bottom (y0), then Left-to-Right (x0)
        self.spans.sort(key=lambda item: (item[0].y0, item[0].x0))

    def query_style(
            self,
            norm_left: float,
            norm_top: float,
            norm_right: float,
            norm_bottom: float,
            node_text: str = ""
    ) -> Dict[str, Any]:
        """Finds best matching font style using spatial overlap, falling back to text search."""
        style_info = {
            "font_name": None,
            "font_size": None,
            "color_hex": None,
            "is_bold": False,
            "is_italic": False,
            "fitz_text": None,  # Captured PyMuPDF raw text
        }

        clean_node_text = node_text.strip().lower()
        best_span = None

        # -------------------------------------------------------------
        # METHOD 1: Spatial Overlap Match (if valid coordinates exist)
        # -------------------------------------------------------------
        if norm_top != float("inf") and norm_left != float("inf"):
            if norm_right <= norm_left:
                norm_right = norm_left + 0.05
            if norm_bottom <= norm_top:
                norm_bottom = norm_top + 0.02

            target_rect = fitz.Rect(
                norm_left * self.page_w,
                norm_top * self.page_h,
                norm_right * self.page_w,
                norm_bottom * self.page_h,
            )
            search_rect = target_rect + (-3, -3, 3, 3)

            max_overlap_area = 0.0

            for span_rect, span in self.spans:
                intersection = search_rect & span_rect
                if not intersection.is_empty:
                    overlap_area = intersection.width * intersection.height
                    span_text = span.get("text", "").strip().lower()

                    if clean_node_text and (span_text in clean_node_text or clean_node_text in span_text):
                        best_span = span
                        break

                    if overlap_area > max_overlap_area:
                        max_overlap_area = overlap_area
                        best_span = span

        # -------------------------------------------------------------
        # METHOD 2: Text Matching Fallback (Crucial for Table Cells without BBox)
        # -------------------------------------------------------------
        if not best_span and clean_node_text:
            for _, span in self.spans:
                span_text = span.get("text", "").strip().lower()
                if span_text and (
                        span_text == clean_node_text or span_text in clean_node_text or clean_node_text in span_text):
                    best_span = span
                    break

        # Populate Style Metadata if a span was found
        if best_span:
            font_name = best_span.get("font", "")
            style_info["font_name"] = font_name
            style_info["font_size"] = round(best_span.get("size", 0.0), 2)
            style_info["fitz_text"] = best_span.get("text", "").strip()

            color_int = best_span.get("color", 0)
            style_info["color_hex"] = f"#{color_int:06x}"

            flags = best_span.get("flags", 0)
            style_info["is_italic"] = bool(flags & 2) or ("italic" in font_name.lower())
            style_info["is_bold"] = bool(flags & 16) or ("bold" in font_name.lower())

        return style_info

class UUIDCorrelatedNode:
    """Represents a node with spatial coordinates normalized to top-left origin."""

    def __init__(self, docling_item: Any, level: int = 0, self_ref: Optional[str] = None):
        self.id: str = str(uuid.uuid4())
        self.parent_id: Optional[str] = None
        self.self_ref: Optional[str] = self_ref or getattr(docling_item, "self_ref", None)

        self.parent_cref: Optional[str] = None
        if hasattr(docling_item, "parent") and docling_item.parent:
            parent_obj = docling_item.parent
            self.parent_cref = getattr(parent_obj, "cref", str(parent_obj))

        self.level: int = level
        self.name : Optional[str] = docling_item.__class__.__name__

        if isinstance(docling_item, str):
            self.label = docling_item.upper()
        else:
            label_attr = getattr(docling_item, "label", type(docling_item).__name__)
            self.label = label_attr.value if hasattr(label_attr, "value") else str(label_attr)

        self.text: str = getattr(docling_item, "text", "").strip() if not isinstance(docling_item, str) else ""
        self.children: List["UUIDCorrelatedNode"] = []

        # Unified Spatial Bounds (0.0 to 1.0 relative page coordinates)
        self.page_no: int = 0
        self.norm_top: float = float("inf")
        self.norm_left: float = float("inf")
        self.norm_bottom: float = 0.0
        self.norm_right: float = 0.0

        # PyMuPDF Font / Style Metadata
        self.font_name: Optional[str] = None
        self.font_size: Optional[float] = None
        self.color_hex: Optional[str] = None
        self.is_bold: bool = False
        self.is_italic: bool = False

        # Cross-verification field: The exact text captured from PyMuPDF span
        self.fitz_text: Optional[str] = None


class UUIDTreeBuilder:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

        print("1. Configuring Docling Pipeline for Table/OCR Extraction...")

        # Enable Table Structure Recognition and OCR
        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_table_structure = True  # Extracts rows, columns, and cells
        pipeline_options.do_ocr = True  # Fallback OCR for scanned tables/images

        converter = DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)
            }
        )

        print("2. Converting Document with Docling...")
        docling_result = converter.convert(pdf_path)
        self.docling_doc = docling_result.document
        self.fitz_doc = fitz.open(pdf_path)

        print("3. Pre-indexing Page Text Spans into Spatial Cache...")
        self.page_style_caches: Dict[int, PageStyleCache] = {
            page.number + 1: PageStyleCache(page) for page in self.fitz_doc
        }
        self.self_ref_to_uuid: Dict[str, str] = {}
        self.uuid_to_node: Dict[str, UUIDCorrelatedNode] = {}



    def _apply_style_from_cache(self, node: UUIDCorrelatedNode):
        """Looks up style info from the pre-computed page cache."""
        if node.page_no in self.page_style_caches:
            cache = self.page_style_caches[node.page_no]
            styles = cache.query_style(
                norm_left=node.norm_left,
                norm_top=node.norm_top,
                norm_right=node.norm_right,
                norm_bottom=node.norm_bottom,
                node_text=node.text
            )
            node.font_name = styles["font_name"]
            node.font_size = styles["font_size"]
            node.color_hex = styles["color_hex"]
            node.is_bold = styles["is_bold"]
            node.is_italic = styles["is_italic"]
            node.fitz_text = styles["fitz_text"]  # Linked fitz string

    def _normalize_docling_bbox(self, prov, page_height: float, page_width: float):
        """Translates Docling coordinates to standard Top-Left relative system (0.0 - 1.0)."""
        bbox = prov.bbox
        l, t, r, b = bbox.l, bbox.t, bbox.r, bbox.b
        coord_origin = getattr(bbox, "coord_origin", "TOP_LEFT")

        if "BOTTOM" in str(coord_origin).upper():
            actual_top = page_height - b
            actual_bottom = page_height - t
        else:
            actual_top = t
            actual_bottom = b

        # Check if coordinates are already normalized (<= 1.0) or in points (> 1.0)
        norm_top = actual_top / page_height if actual_top > 1.0 else actual_top
        norm_left = l / page_width if l > 1.0 else l
        norm_bottom = actual_bottom / page_height if actual_bottom > 1.0 else actual_bottom
        norm_right = r / page_width if r > 1.0 else r

        return norm_top, norm_left, norm_bottom, norm_right

    def _get_or_create_node_by_ref(self, self_ref: str, default_label: str = "CONTAINER",
                                   root_uuid: str = "") -> UUIDCorrelatedNode:
        if self_ref in self.self_ref_to_uuid:
            return self.uuid_to_node[self.self_ref_to_uuid[self_ref]]

        label = default_label
        if "/" in self_ref:
            parts = self_ref.strip("#/").split("/")
            if parts[0]:
                label = parts[0].rstrip("s").upper()

        container_node = UUIDCorrelatedNode(docling_item=label, level=1, self_ref=self_ref)
        self.self_ref_to_uuid[self_ref] = container_node.id
        self.uuid_to_node[container_node.id] = container_node

        if root_uuid and container_node.id != root_uuid:
            root_node = self.uuid_to_node[root_uuid]
            container_node.parent_id = root_uuid
            if container_node not in root_node.children:
                root_node.children.append(container_node)

        return container_node

    def _propagate_bounds(self, node: UUIDCorrelatedNode):
        """Recursively aggregates container bounds based on all nested children."""
        if not node.children:
            return

        for child in node.children:
            self._propagate_bounds(child)
            if child.page_no > 0:
                node.page_no = child.page_no if node.page_no == 0 else min(node.page_no, child.page_no)
                node.norm_top = min(node.norm_top, child.norm_top)
                node.norm_left = min(node.norm_left, child.norm_left)
                node.norm_bottom = max(node.norm_bottom, child.norm_bottom)
                node.norm_right = max(node.norm_right, child.norm_right)

    def sort_tree_spatially(self, node: UUIDCorrelatedNode, column_tolerance: float = 0.28):
        """Sorts children spatially using Column-Aware Reading Order."""
        if not node.children:
            return

        def column_reading_order_key(child: UUIDCorrelatedNode):
            p = child.page_no
            col_zone = round(child.norm_left / column_tolerance) * column_tolerance if child.norm_left != float(
                "inf") else 0.0
            y_pos = child.norm_top if child.norm_top != float("inf") else 0.0
            return (p, col_zone, y_pos)

        node.children.sort(key=column_reading_order_key)

        for child in node.children:
            self.sort_tree_spatially(child, column_tolerance=column_tolerance)

    def _process_image_item(self, doc_item: Any, node: UUIDCorrelatedNode):
        """Extracts and attaches PIL Image data as a Base64 encoded string."""
        image_obj: Optional[Image.Image] = None

        # Try docling get_image method or image attribute
        if hasattr(doc_item, "get_image"):
            try:
                image_obj = doc_item.get_image(self.docling_doc)
            except Exception:
                image_obj = getattr(doc_item, "image", None)
        else:
            image_obj = getattr(doc_item, "image", None)

        if image_obj:
            node.is_image = True
            node.image_width = image_obj.width
            node.image_height = image_obj.height
            node.image_format = image_obj.format or "PNG"

            # Convert Image to Base64 byte string
            buffered = io.BytesIO()
            img_format = (
                node.image_format
                if node.image_format.upper() in ["JPEG", "PNG", "WEBP"]
                else "PNG"
            )
            image_obj.save(buffered, format=img_format)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            node.image_base64 = f"data:image/{img_format.lower()};base64,{img_str}"
            
    def build_tree(self) -> UUIDCorrelatedNode:
        body_item = self.docling_doc.body
        body_self_ref = getattr(body_item, "self_ref", "#/body")

        root_node = UUIDCorrelatedNode(body_item, level=0, self_ref=body_self_ref)
        root_node.label = "BODY"
        self.self_ref_to_uuid[body_self_ref] = root_node.id
        self.uuid_to_node[root_node.id] = root_node

        all_nodes: List[UUIDCorrelatedNode] = []

        # Iterate through standard document items
        for doc_item, level in self.docling_doc.iterate_items():
            node = UUIDCorrelatedNode(doc_item, level)
            all_nodes.append(node)
            self.uuid_to_node[node.id] = node

            if node.self_ref:
                self.self_ref_to_uuid[node.self_ref] = node.id

            if hasattr(doc_item, "prov") and doc_item.prov:
                prov = doc_item.prov[0]
                node.page_no = prov.page_no

                pdf_page = self.fitz_doc[node.page_no - 1]
                page_w, page_h = pdf_page.rect.width, pdf_page.rect.height

                node.norm_top, node.norm_left, node.norm_bottom, node.norm_right = (
                    self._normalize_docling_bbox(prov, page_h, page_w)
                )

                self._apply_style_from_cache(node)
                
            # Check and process images for Picture items
            if node.label.upper() in ["PICTURE", "IMAGE", "FIGURE"]:
                self._process_image_item(doc_item, node)


        # Extract nested Table Cells if present
        if hasattr(self.docling_doc, "tables"):
            for table_idx, table in enumerate(self.docling_doc.tables):
                table_ref = getattr(table, "self_ref", f"#/tables/{table_idx}")
                table_node = self._get_or_create_node_by_ref(self_ref=table_ref, default_label="TABLE",
                                                             root_uuid=root_node.id)

                # Extract individual cells inside table
                if hasattr(table, "data") and hasattr(table.data, "table_cells"):
                    for cell in table.data.table_cells:
                        cell_node = UUIDCorrelatedNode(cell, level=2)
                        cell_node.label = "TABLE_CELL"
                        cell_node.text = getattr(cell, "text", "").strip()
                        cell_node.parent_id = table_node.id

                        if hasattr(cell, "prov") and cell.prov:
                            prov = cell.prov[0]
                            cell_node.page_no = prov.page_no
                            pdf_page = self.fitz_doc[cell_node.page_no - 1]
                            cell_node.norm_top, cell_node.norm_left, cell_node.norm_bottom, cell_node.norm_right = (
                                self._normalize_docling_bbox(prov, pdf_page.rect.height, pdf_page.rect.width)
                            )

                        else:
                            # Fallback: Inherit page number from parent table node
                            cell_node.page_no = table_node.page_no or 1

                        self._apply_style_from_cache(cell_node)
                        table_node.children.append(cell_node)

        # Attach parent-child relationships
        for node in all_nodes:
            parent_ref = node.parent_cref or body_self_ref
            parent_node = self._get_or_create_node_by_ref(self_ref=parent_ref, root_uuid=root_node.id)
            node.parent_id = parent_node.id
            if node not in parent_node.children:
                parent_node.children.append(node)

        self._propagate_bounds(root_node)
        self.sort_tree_spatially(root_node, column_tolerance=0.28)

        return root_node

    def print_uuid_tree(self, node: UUIDCorrelatedNode, prefix: str = "", is_last: bool = True):
        parent_str = f" [parent_id: ...{node.parent_id[-8:]}]" if node.parent_id else " [parent_id: None]"
        id_str = f"[id: ...{node.id[-8:]}]"
        ref_str = f" [{node.self_ref}]" if node.self_ref else ""
        # Display Docling text vs PyMuPDF text for cross-verification
        docling_text = f' -> Docling: "{node.text[:25]}"' if node.text else ""
        fitz_text = f' | Fitz: "{node.fitz_text[:25]}"' if node.fitz_text else " | Fitz: [NO MATCH]"

        img_str = (
            f" [IMAGE: {node.image_width}x{node.image_height}]" if node.is_image else ""
        )
        
        # Style string formatting
        style_str = ""
        if node.font_name:
            font_style = []
            if node.is_bold:
                font_style.append("Bold")
            if node.is_italic:
                font_style.append("Italic")
            style_desc = f" ({', '.join(font_style)})" if font_style else ""
            style_str = f" [Font: {node.font_name} @ {node.font_size}pt{style_desc}, Color: {node.color_hex}]"


        docling_name_label_str = node.name +"-"+node.label
        connector = "└── " if is_last else "├── "
        print(f"[{docling_name_label_str}]{prefix}{connector}[{node.label}]{ref_str} {id_str}{parent_str}{style_str}{img_str}{docling_text}{fitz_text}")

        count = len(node.children)
        child_prefix = prefix + ("    " if is_last else "│   ")

        for idx, child in enumerate(node.children):
            child_is_last = (idx == count - 1)
            self.print_uuid_tree(child, prefix=child_prefix, is_last=child_is_last)



if __name__ == "__main__":
    builder = UUIDTreeBuilder("pdfs/csg.pdf")
    root = builder.build_tree()

    print("\nVisualizing Tree with Table Cell Sub-Nodes:")
    print("=" * 80)
    builder.print_uuid_tree(root)