import uuid
import fitz  # PyMuPDF
import base64
import io
from typing import List, Dict, Any, Optional, Tuple
from PIL import Image

# Docling imports
from docling.document_converter import DocumentConverter, PdfFormatOption
from docling.datamodel.pipeline_options import (
    PdfPipelineOptions,
    TableStructureOptions,
    TableFormerMode,
)
from docling.datamodel.base_models import InputFormat


class PageStyleCache:
    """Pre-loads and indexes all PyMuPDF text spans for a page by bounding box and text."""

    def __init__(self, page: fitz.Page):
        self.page_no = page.number + 1
        self.page_w = page.rect.width
        self.page_h = page.rect.height
        self.spans: List[Tuple[fitz.Rect, Dict[str, Any]]] = []
        self._build_index(page)

    def _build_index(self, page: fitz.Page):
        page_dict = page.get_text("dict")
        for block in page_dict.get("blocks", []):
            if "lines" not in block:
                continue
            for line in block["lines"]:
                for span in line["spans"]:
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    bbox = fitz.Rect(span["bbox"])
                    self.spans.append((bbox, span))

        self.spans.sort(key=lambda item: (item[0].y0, item[0].x0))

    def query_style(
        self,
        norm_left: float,
        norm_top: float,
        norm_right: float,
        norm_bottom: float,
        node_text: str = "",
    ) -> Dict[str, Any]:
        style_info = {
            "font_name": None,
            "font_size": None,
            "color_hex": None,
            "is_bold": False,
            "is_italic": False,
            "fitz_text": None,
        }

        clean_node_text = node_text.strip().lower()
        best_span = None

        if norm_top != float("inf") and norm_left != float("inf"):
            if norm_right <= norm_left:
                norm_right = norm_left + 0.05
            if norm_bottom <= norm_top:
                norm_bottom = norm_top + 0.02

            search_rect = fitz.Rect(
                norm_left * self.page_w,
                norm_top * self.page_h,
                norm_right * self.page_w,
                norm_bottom * self.page_h,
            ) + (-3, -3, 3, 3)

            max_overlap = 0.0
            for span_rect, span in self.spans:
                intersection = search_rect & span_rect
                if not intersection.is_empty:
                    overlap_area = intersection.width * intersection.height
                    span_text = span.get("text", "").strip().lower()
                    if clean_node_text and (span_text in clean_node_text or clean_node_text in span_text):
                        best_span = span
                        break
                    if overlap_area > max_overlap:
                        max_overlap = overlap_area
                        best_span = span

        if not best_span and clean_node_text:
            for _, span in self.spans:
                span_text = span.get("text", "").strip().lower()
                if span_text and (span_text == clean_node_text or span_text in clean_node_text or clean_node_text in span_text):
                    best_span = span
                    break

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
        self.name: Optional[str] = docling_item.__class__.__name__

        if isinstance(docling_item, str):
            self.label = docling_item.upper()
        else:
            label_attr = getattr(docling_item, "label", type(docling_item).__name__)
            self.label = label_attr.value if hasattr(label_attr, "value") else str(label_attr)

        self.text: str = getattr(docling_item, "text", "").strip() if not isinstance(docling_item, str) else ""
        self.children: List["UUIDCorrelatedNode"] = []

        # Unified Spatial Bounds (0.0 to 1.0 relative page coordinates)
        self.page_no: int = 0
        self.column_no: int = 0  # Dynamic Column Assignment
        self.norm_top: float = float("inf")
        self.norm_left: float = float("inf")
        self.norm_bottom: float = 0.0
        self.norm_right: float = 0.0

        # Style Metadata
        self.font_name: Optional[str] = None
        self.font_size: Optional[float] = None
        self.color_hex: Optional[str] = None
        self.is_bold: bool = False
        self.is_italic: bool = False
        self.fitz_text: Optional[str] = None

        # Image Metadata
        self.is_image: bool = False
        self.image_source: Optional[str] = None
        self.image_base64: Optional[str] = None
        self.image_format: Optional[str] = None
        self.image_width: Optional[int] = None
        self.image_height: Optional[int] = None

    @property
    def center_x(self) -> float:
        return (self.norm_left + self.norm_right) / 2.0 if self.norm_left != float("inf") else 0.0

    @property
    def center_y(self) -> float:
        return (self.norm_top + self.norm_bottom) / 2.0 if self.norm_top != float("inf") else 0.0


class UUIDTreeBuilder:

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_table_structure = True
        pipeline_options.do_ocr = True

        # --- ESSENTIAL ADDITIONS FOR VISUAL/GRID DOCUMENTS ---
        pipeline_options.generate_page_images = True
        pipeline_options.generate_picture_images = True
        pipeline_options.generate_table_images = True

        # Helps detect complex visual table structures and grids
        pipeline_options.table_structure_options = TableStructureOptions(
            mode=TableFormerMode.ACCURATE,  # Uses ACCURATE instead of FAST
            do_cell_matching=True,  # Strict cell matching to drawn/implicit grid lines
        )

        converter = DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )

        docling_result = converter.convert(pdf_path)
        self.docling_doc = docling_result.document
        self.fitz_doc = fitz.open(pdf_path)

        self.page_style_caches: Dict[int, PageStyleCache] = {
            page.number + 1: PageStyleCache(page) for page in self.fitz_doc
        }
        self.self_ref_to_uuid: Dict[str, str] = {}
        self.uuid_to_node: Dict[str, UUIDCorrelatedNode] = {}

    def _assign_page_columns(
        self, page_nodes: List[UUIDCorrelatedNode], default_cols: int = 18
    ):
        """Dynamically estimates grid/column positioning based on document content width."""
        valid_nodes = [n for n in page_nodes if n.norm_left != float("inf")]
        if not valid_nodes:
            return

        # Check x-span of elements on page
        min_x = min(n.norm_left for n in valid_nodes)
        max_x = max(n.norm_right for n in valid_nodes)
        total_span = max_x - min_x

        if total_span <= 0:
            return

        # Assign column based on relative horizontal percentage across 18 grid slots
        for node in valid_nodes:
            rel_pos = (node.center_x - min_x) / total_span
            col_idx = int(rel_pos * default_cols)
            node.column_no = max(0, min(col_idx, default_cols - 1))

    def _normalize_docling_bbox(self, prov, page_height: float, page_width: float):
        bbox = prov.bbox
        l, t, r, b = bbox.l, bbox.t, bbox.r, bbox.b
        coord_origin = getattr(bbox, "coord_origin", "TOP_LEFT")

        if "BOTTOM" in str(coord_origin).upper():
            actual_top = page_height - b
            actual_bottom = page_height - t
        else:
            actual_top = t
            actual_bottom = b

        norm_top = actual_top / page_height if actual_top > 1.0 else actual_top
        norm_left = l / page_width if l > 1.0 else l
        norm_bottom = actual_bottom / page_height if actual_bottom > 1.0 else actual_bottom
        norm_right = r / page_width if r > 1.0 else r

        return norm_top, norm_left, norm_bottom, norm_right

    def _apply_style_from_cache(self, node: UUIDCorrelatedNode):
        if node.page_no in self.page_style_caches:
            cache = self.page_style_caches[node.page_no]
            styles = cache.query_style(
                norm_left=node.norm_left,
                norm_top=node.norm_top,
                norm_right=node.norm_right,
                norm_bottom=node.norm_bottom,
                node_text=node.text,
            )
            node.font_name = styles["font_name"]
            node.font_size = styles["font_size"]
            node.color_hex = styles["color_hex"]
            node.is_bold = styles["is_bold"]
            node.is_italic = styles["is_italic"]
            node.fitz_text = styles["fitz_text"]

    def _process_image_item(self, doc_item: Any, node: UUIDCorrelatedNode):
        image_obj: Optional[Image.Image] = None
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

            buffered = io.BytesIO()
            img_format = node.image_format if node.image_format.upper() in ["JPEG", "PNG", "WEBP"] else "PNG"
            image_obj.save(buffered, format=img_format)
            img_str = base64.b64encode(buffered.getvalue()).decode("utf-8")
            node.image_base64 = f"data:image/{img_format.lower()};base64,{img_str}"

    def _get_or_create_node_by_ref(
        self, self_ref: str, default_label: str = "CONTAINER", root_uuid: str = ""
    ) -> UUIDCorrelatedNode:
        if self_ref in self.self_ref_to_uuid:
            return self.uuid_to_node[self.self_ref_to_uuid[self_ref]]

        label = default_label
        if "/" in self_ref:
            parts = self_ref.strip("#/").split("/")
            if parts[0]:
                extracted_label = parts[0].rstrip("s").upper()
                # If label is generic or UNSPECIFIED, treat as a generic CONTAINER
                label = (
                    "CONTAINER" if extracted_label == "UNSPECIFIED" else extracted_label
                )

        container_node = UUIDCorrelatedNode(
            docling_item=label, level=1, self_ref=self_ref
        )
        self.self_ref_to_uuid[self_ref] = container_node.id
        self.uuid_to_node[container_node.id] = container_node

        if root_uuid and container_node.id != root_uuid:
            root_node = self.uuid_to_node[root_uuid]
            container_node.parent_id = root_uuid
            if container_node not in root_node.children:
                root_node.children.append(container_node)

        return container_node

    def _propagate_bounds(self, node: UUIDCorrelatedNode):
        if not node.children:
            return

        for child in node.children:
            self._propagate_bounds(child)
            if child.page_no > 0:
                node.page_no = (
                    child.page_no
                    if node.page_no == 0
                    else min(node.page_no, child.page_no)
                )

                # Update bounds avoiding infinity bugs
                if child.norm_top != float("inf"):
                    node.norm_top = min(node.norm_top, child.norm_top)
                if child.norm_left != float("inf"):
                    node.norm_left = min(node.norm_left, child.norm_left)

                node.norm_bottom = max(node.norm_bottom, child.norm_bottom)
                node.norm_right = max(node.norm_right, child.norm_right)

    def sort_tree_spatially(self, node: UUIDCorrelatedNode):
        """Sorts nodes deterministically: Page -> Column -> Vertical Y-Coordinate -> Horizontal X-Coordinate."""
        if not node.children:
            return

        # Associate inline/side-by-side images with vertically overlapping text blocks
        page_groups: Dict[int, List[UUIDCorrelatedNode]] = {}
        for child in node.children:
            page_groups.setdefault(child.page_no, []).append(child)

        # Re-sort elements per page by Reading Flow Order
        sorted_children = []
        for p_no in sorted(page_groups.keys()):
            p_nodes = page_groups[p_no]

            def reading_order_key(item: UUIDCorrelatedNode):
                return (
                    item.page_no,
                    item.column_no,
                    item.norm_top if item.norm_top != float("inf") else 0.0,
                    item.norm_left if item.norm_left != float("inf") else 0.0,
                )

            p_nodes.sort(key=reading_order_key)
            sorted_children.extend(p_nodes)

        node.children = sorted_children

        for child in node.children:
            self.sort_tree_spatially(child)

    def build_tree(self) -> UUIDCorrelatedNode:
        body_item = self.docling_doc.body
        body_self_ref = getattr(body_item, "self_ref", "#/body")

        root_node = UUIDCorrelatedNode(body_item, level=0, self_ref=body_self_ref)
        root_node.label = "BODY"
        self.self_ref_to_uuid[body_self_ref] = root_node.id
        self.uuid_to_node[root_node.id] = root_node

        all_nodes: List[UUIDCorrelatedNode] = []
        nodes_by_page: Dict[int, List[UUIDCorrelatedNode]] = {}

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
                nodes_by_page.setdefault(node.page_no, []).append(node)

            if node.label.upper() in ["PICTURE", "IMAGE", "FIGURE"]:
                self._process_image_item(doc_item, node)

        # Process per-page columns based on bounding box geometry
        for page_no, p_nodes in nodes_by_page.items():
            self._assign_page_columns(p_nodes)

        # Tables processing
        if hasattr(self.docling_doc, "tables"):
            for table_idx, table in enumerate(self.docling_doc.tables):
                table_ref = getattr(table, "self_ref", f"#/tables/{table_idx}")
                table_node = self._get_or_create_node_by_ref(
                    self_ref=table_ref, default_label="TABLE", root_uuid=root_node.id
                )

                if hasattr(table, "data") and hasattr(table.data, "table_cells"):
                    rows_dict: Dict[int, List[Any]] = {}
                    for cell in table.data.table_cells:
                        # Docling table cells have row_offset_idx (or fallback to start_row_offset_idx)
                        row_idx = getattr(
                            cell,
                            "row_offset_idx",
                            getattr(cell, "start_row_offset_idx", 0),
                        )
                        rows_dict.setdefault(row_idx, []).append(cell)


                    # 2. Iterate through sorted rows and create TABLE_ROW nodes
                    for row_idx in sorted(rows_dict.keys()):
                        row_cells = rows_dict[row_idx]

                        # Create the intermediate TABLE_ROW node
                        row_self_ref = f"{table_ref}/rows/{row_idx}"
                        row_node = UUIDCorrelatedNode(docling_item="TABLE_ROW", level=2, self_ref=row_self_ref)
                        row_node.label = "TABLE_ROW"
                        row_node.parent_id = table_node.id

                        # Sort cells within the row left-to-right by column index
                        row_cells.sort(key=lambda c: getattr(c, "col_offset_idx", getattr(c, "start_col_offset_idx", 0)))

                        for cell in row_cells:
                            cell_node = UUIDCorrelatedNode(cell, level=2)
                            cell_node.label = "TABLE_CELL"
                            cell_node.text = getattr(cell, "text", "").strip()
                            cell_node.parent_id = row_node.id

                            if hasattr(cell, "prov") and cell.prov:
                                prov = cell.prov[0]
                                cell_node.page_no = prov.page_no
                                pdf_page = self.fitz_doc[cell_node.page_no - 1]
                                (
                                    cell_node.norm_top,
                                    cell_node.norm_left,
                                    cell_node.norm_bottom,
                                    cell_node.norm_right,
                                ) = self._normalize_docling_bbox(
                                    prov, pdf_page.rect.height, pdf_page.rect.width
                                )
                            else:
                                cell_node.page_no = table_node.page_no or 1

                            self._apply_style_from_cache(cell_node)

                        table_node.children.append(row_node)

        # Parent-child linking
        for node in all_nodes:
            parent_ref = node.parent_cref or body_self_ref
            parent_node = self._get_or_create_node_by_ref(
                self_ref=parent_ref, root_uuid=root_node.id
            )
            node.parent_id = parent_node.id
            if node not in parent_node.children:
                parent_node.children.append(node)

        self._propagate_bounds(root_node)
        self.sort_tree_spatially(root_node)

        return root_node

    def print_uuid_tree(self, node: UUIDCorrelatedNode, prefix: str = "", is_last: bool = True):
        parent_str = f" [parent_id: ...{node.parent_id[-8:]}]" if node.parent_id else " [parent_id: None]"
        id_str = f"[id: ...{node.id[-8:]}]"
        ref_str = f" [{node.self_ref}]" if node.self_ref else ""
        col_str = f" [Col: {node.column_no}]"
        docling_text = f' -> Docling: "{node.text[:25]}"' if node.text else ""
        fitz_text = f' | Fitz: "{node.fitz_text[:25]}"' if node.fitz_text else " | Fitz: [NO MATCH]"

        img_str = f" [IMAGE: {node.image_width}x{node.image_height}]" if node.is_image else ""

        style_str = ""
        if node.font_name:
            font_style = []
            if node.is_bold:
                font_style.append("Bold")
            if node.is_italic:
                font_style.append("Italic")
            style_desc = f" ({', '.join(font_style)})" if font_style else ""
            style_str = f" [Font: {node.font_name} @ {node.font_size}pt{style_desc}, Color: {node.color_hex}]"

        docling_name_label_str = node.name + "-" + node.label
        connector = "└── " if is_last else "├── "
        print(
            f"[{docling_name_label_str}]{prefix}{connector}[{node.label}]{ref_str}{col_str} {id_str}{parent_str}{style_str}{img_str}{docling_text}{fitz_text}"
        )

        count = len(node.children)
        child_prefix = prefix + ("    " if is_last else "│   ")

        for idx, child in enumerate(node.children):
            child_is_last = idx == count - 1
            self.print_uuid_tree(child, prefix=child_prefix, is_last=child_is_last)


if __name__ == "__main__":
    builder = UUIDTreeBuilder("pdfs/ptable.pdf")
    root = builder.build_tree()

    print("\nVisualizing Tree with Correct Multi-Column & Image Spatial Alignment:")
    print("=" * 80)
    builder.print_uuid_tree(root)