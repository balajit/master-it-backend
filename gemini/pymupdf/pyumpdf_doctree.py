import fitz  # PyMuPDF
import re
from typing import List, Dict, Any, Optional
from collections import Counter


class GeneralizedPDFParser:
    """Parses any PDF into a Docling-like JSON Pointer tree dynamically

    without hardcoding specific text strings or fixed font sizes.
    """

    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)

        # Output Collections (Matching Docling Schema)
        self.texts: List[Dict[str, Any]] = []
        self.tables: List[Dict[str, Any]] = []
        self.groups: List[Dict[str, Any]] = []
        self.ref_map: Dict[str, Any] = {}

        # Statistical Font Thresholds (Computed in Pass 1)
        self.body_font_size: float = 10.0
        self.header_font_threshold: float = 12.0
        self.title_font_threshold: float = 16.0

        # Root Node
        self.body = {
            "self_ref": "#/body",
            "label": "BODY",
            "children": []
        }
        self.ref_map["#/body"] = self.body

    def _compute_typography_statistics(self):
        """Pass 1: Computes font frequency statistics dynamically for the PDF."""
        font_sizes = []

        for page in self.doc:
            text_dict = page.get_text("dict")
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # Text block
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            text = span.get("text", "").strip()
                            if text:
                                font_sizes.append(round(span.get("size", 0), 1))

        if not font_sizes:
            return

        # Body font is statistically the most common font size in a document
        size_counts = Counter(font_sizes)
        self.body_font_size = size_counts.most_common(1)[0][0]

        # Calculate dynamic thresholds relative to the document's base body font
        unique_sizes = sorted(list(set(font_sizes)))
        larger_sizes = [s for s in unique_sizes if s > self.body_font_size]

        if len(larger_sizes) >= 2:
            self.header_font_threshold = larger_sizes[0]
            self.title_font_threshold = larger_sizes[1]
        elif len(larger_sizes) == 1:
            self.header_font_threshold = larger_sizes[0]
            self.title_font_threshold = larger_sizes[0] + 2.0
        else:
            self.header_font_threshold = self.body_font_size + 1.5
            self.title_font_threshold = self.body_font_size + 3.5

    def _classify_label(self, text: str, max_font_size: float, is_bold: bool) -> str:
        """Dynamically infers semantic label based on relative typography and regex primitives."""
        clean_text = text.strip()

        # Generic List Item regex primitive (numbers, bullets, letters followed by dot/paren)
        list_pattern = r'^(\d+[\.\)]|[a-zA-Z][\.\)]|[•\-\*■])\s+'

        if max_font_size >= self.title_font_threshold:
            return "TITLE"
        elif max_font_size >= self.header_font_threshold or (is_bold and len(clean_text) < 80):
            return "SECTION_HEADER"
        elif re.match(list_pattern, clean_text):
            return "LIST_ITEM"
        else:
            return "PARAGRAPH"

    def parse(self):
        """Pass 2: Builds the tree hierarchy dynamically."""
        self._compute_typography_statistics()

        text_counter = 0
        group_counter = 0
        table_counter = 0

        for page_idx, page in enumerate(self.doc):
            page_num = page_idx + 1

            # 1. Native Table Extraction
            tabs = page.find_tables()
            table_rects = []
            for tab in tabs:
                table_counter += 1
                table_ref = f"#/tables/{table_counter}"
                table_rects.append(tab.rect)

                table_obj = {
                    "self_ref": table_ref,
                    "label": "TABLE",
                    "parent": {"cref": "#/body"},
                    "prov": [{"page_no": page_num, "bbox": list(tab.rect)}],
                    "data": tab.extract()
                }
                self.tables.append(table_obj)
                self.ref_map[table_ref] = table_obj
                self.body["children"].append({"cref": table_ref})

            # 2. Text Block Processing
            text_page = page.get_text("dict")
            current_group: Optional[Dict[str, Any]] = None

            for block in text_page.get("blocks", []):
                if block.get("type") != 0:
                    continue

                block_rect = fitz.Rect(block["bbox"])
                # Ignore text inside extracted tables
                if any(block_rect.intersects(tr) for tr in table_rects):
                    continue

                block_lines = []
                max_font_size = 0.0
                is_bold = False

                for line in block.get("lines", []):
                    line_str = "".join([span["text"] for span in line.get("spans", [])]).strip()
                    if line_str:
                        block_lines.append(line_str)
                        for span in line.get("spans", []):
                            max_font_size = max(max_font_size, span.get("size", 0.0))
                            if span.get("flags", 0) & 2 ** 4:  # PyMuPDF Bold flag
                                is_bold = True

                if not block_lines:
                    continue

                full_text = " ".join(block_lines)
                label = self._classify_label(full_text, max_font_size, is_bold)

                # Create Text Item
                text_ref = f"#/texts/{text_counter}"
                text_counter += 1

                text_obj = {
                    "self_ref": text_ref,
                    "label": label,
                    "text": full_text,
                    "prov": [{"page_no": page_num, "bbox": block["bbox"]}],
                    "parent": None
                }
                self.texts.append(text_obj)
                self.ref_map[text_ref] = text_obj

                # 3. Dynamic Structural Grouping
                if label == "LIST_ITEM":
                    if not current_group:
                        group_ref = f"#/groups/{group_counter}"
                        group_counter += 1

                        current_group = {
                            "self_ref": group_ref,
                            "label": "LIST_GROUP",
                            "parent": {"cref": "#/body"},
                            "children": []
                        }
                        self.groups.append(current_group)
                        self.ref_map[group_ref] = current_group
                        self.body["children"].append({"cref": group_ref})

                    text_obj["parent"] = {"cref": current_group["self_ref"]}
                    current_group["children"].append({"cref": text_ref})
                else:
                    current_group = None
                    text_obj["parent"] = {"cref": "#/body"}
                    self.body["children"].append({"cref": text_ref})

        return self.body, self.ref_map


def print_tree(node, ref_map: dict, prefix: str = "", is_last: bool = True):
    """Prints the generalized document hierarchy."""
    label = node.get("label", "NODE")
    self_ref = node.get("self_ref", "")
    id_str = f" [{self_ref}]" if self_ref else ""

    text_snippet = ""
    if "text" in node:
        clean_text = node["text"].strip().replace("\n", " ")
        if len(clean_text) > 40:
            clean_text = clean_text[:37] + "..."
        text_snippet = f' -> "{clean_text}"'

    connector = "└── " if is_last else "├── "
    print(f"{prefix}{connector}[{label}]{id_str}{text_snippet}")

    children = node.get("children", [])
    child_prefix = prefix + ("    " if is_last else "│   ")
    count = len(children)

    for idx, child in enumerate(children):
        child_is_last = (idx == count - 1)
        cref = child.get("cref") if isinstance(child, dict) else child
        child_node = ref_map.get(cref)

        if child_node:
            print_tree(child_node, ref_map, prefix=child_prefix, is_last=child_is_last)


# --- Execution ---
if __name__ == "__main__":
    parser = GeneralizedPDFParser("pdfs/csg.pdf")
    body_root, global_ref_map = parser.parse()

    print(f"Detected Body Font Size: {parser.body_font_size}pt")
    print(f"Header Font Threshold:   {parser.header_font_threshold}pt")
    print(f"Title Font Threshold:    {parser.title_font_threshold}pt")
    print("=" * 60)
    print_tree(body_root, global_ref_map)