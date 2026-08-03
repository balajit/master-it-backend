import uuid
import fitz  # PyMuPDF
from typing import List, Dict, Any, Optional
from docling.document_converter import DocumentConverter


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


class UUIDTreeBuilder:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path

        print("1. Converting Document with Docling...")
        converter = DocumentConverter()
        docling_result = converter.convert(pdf_path)
        self.docling_doc = docling_result.document
        self.fitz_doc = fitz.open(pdf_path)

        self.self_ref_to_uuid: Dict[str, str] = {}
        self.uuid_to_node: Dict[str, UUIDCorrelatedNode] = {}

    def _normalize_docling_bbox(self, prov, page_height: float, page_width: float):
        """
        Translates Docling coordinates to a standard Top-Left relative coordinate system (0.0 - 1.0).
        """
        bbox = prov.bbox
        # Docling BBox object handling
        l, t, r, b = bbox.l, bbox.t, bbox.r, bbox.b
        coord_origin = getattr(bbox, "coord_origin", "TOP_LEFT")

        if "BOTTOM" in str(coord_origin).upper():
            # Invert Y coordinate if origin is Bottom-Left
            actual_top = page_height - b
        else:
            actual_top = t

        norm_top = actual_top / page_height if page_height else actual_top
        norm_left = l / page_width if page_width else l

        return norm_top, norm_left

    def _get_or_create_node_by_ref(self, self_ref: str, default_label: str = "CONTAINER", root_uuid: str = "") -> UUIDCorrelatedNode:
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
        """Derives container bounds from leaf children."""
        if not node.children:
            return

        for child in node.children:
            self._propagate_bounds(child)
            if child.page_no > 0:
                node.page_no = child.page_no if node.page_no == 0 else min(node.page_no, child.page_no)
                node.norm_top = min(node.norm_top, child.norm_top)
                node.norm_left = min(node.norm_left, child.norm_left)

    def sort_tree_spatially(self, node: UUIDCorrelatedNode):
        """Sorts nodes by Page -> Column (X-zone) -> Top-to-Bottom (Y)."""
        if not node.children:
            return

        def sort_key(child: UUIDCorrelatedNode):
            # Page number primary
            p = child.page_no
            # Top relative position secondary (rounded to 1.5% of page height to group lines)
            y = round(child.norm_top, 2) if child.norm_top != float("inf") else 0
            # Left relative position tertiary
            x = child.norm_left if child.norm_left != float("inf") else 0
            return (p, y, x)

        node.children.sort(key=sort_key)

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

        for doc_item, level in self.docling_doc.iterate_items():
            node = UUIDCorrelatedNode(doc_item, level)
            all_nodes.append(node)
            self.uuid_to_node[node.id] = node

            if node.self_ref:
                self.self_ref_to_uuid[node.self_ref] = node.id

            if hasattr(doc_item, "prov") and doc_item.prov:
                prov = doc_item.prov[0]
                node.page_no = prov.page_no

                # Fetch page dimensions from PyMuPDF for precise normalization
                pdf_page = self.fitz_doc[node.page_no - 1]
                page_w, page_h = pdf_page.rect.width, pdf_page.rect.height

                # Get normalized Top-Left coordinates
                node.norm_top, node.norm_left = self._normalize_docling_bbox(prov, page_h, page_w)

        # Attach parent-child relationships
        for node in all_nodes:
            parent_ref = node.parent_cref or body_self_ref
            parent_node = self._get_or_create_node_by_ref(self_ref=parent_ref, root_uuid=root_node.id)
            node.parent_id = parent_node.id
            if node not in parent_node.children:
                parent_node.children.append(node)

        # Calculate container dimensions and sort
        self._propagate_bounds(root_node)
        self.sort_tree_spatially(root_node)

        return root_node

    def print_uuid_tree(self, node: UUIDCorrelatedNode, prefix: str = "", is_last: bool = True):
        parent_str = f" [parent_id: ...{node.parent_id[-8:]}]" if node.parent_id else " [parent_id: None]"
        id_str = f"[id: ...{node.id[-8:]}]"
        ref_str = f" [{node.self_ref}]" if node.self_ref else ""
        text_info = f' -> "{node.text[:35]}..."' if node.text else ""

        connector = "└── " if is_last else "├── "
        print(f"{prefix}{connector}[{node.label}]{ref_str} {id_str}{parent_str}{text_info}")

        count = len(node.children)
        child_prefix = prefix + ("    " if is_last else "│   ")

        for idx, child in enumerate(node.children):
            child_is_last = (idx == count - 1)
            self.print_uuid_tree(child, prefix=child_prefix, is_last=child_is_last)


if __name__ == "__main__":
    builder = UUIDTreeBuilder("pdfs/csg.pdf")
    root = builder.build_tree()

    print("\nVisualizing Tree with Fixed Coordinate Sorting:")
    print("=" * 80)
    builder.print_uuid_tree(root)