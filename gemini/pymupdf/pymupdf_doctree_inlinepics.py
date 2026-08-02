import fitz  # PyMuPDF
import re
from typing import List, Dict, Any, Optional


class SpatiallyIntegratedPDFParser:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)

        self.texts: List[Dict[str, Any]] = []
        self.blank_lines: List[Dict[str, Any]] = []
        self.ref_map: Dict[str, Any] = {}

        self.body = {"self_ref": "#/body", "label": "BODY", "children": []}
        self.ref_map["#/body"] = self.body

    def extract_page_elements(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        """Extracts both text blocks and drawn lines, tagging them with Y-coordinates for sorting."""
        page_elements = []

        # 1. Extract Vector Lines
        drawings = page.get_drawings()
        for path in drawings:
            for item in path.get("items", []):
                if item[0] == "l":  # Line command: ('l', p1, p2)
                    p1, p2 = item[1], item[2]
                    is_horizontal = abs(p1.y - p2.y) < 2.0
                    length = abs(p1.x - p2.x)

                    if is_horizontal and length >= 20.0:
                        bbox = [min(p1.x, p2.x), min(p1.y, p2.y) - 2, max(p1.x, p2.x), max(p1.y, p2.y) + 2]
                        page_elements.append({
                            "element_type": "vector_line",
                            "label": "ANSWER_LINE",
                            "bbox": bbox,
                            "top": bbox[1],  # Y-top coordinate for spatial sorting
                            "length": round(length, 2),
                            "page_no": page_num
                        })

        # 2. Extract Text Blocks
        text_page = page.get_text("dict")
        for block in text_page.get("blocks", []):
            if block.get("type") != 0:
                continue

            block_lines = []
            for line in block.get("lines", []):
                line_str = "".join([span["text"] for span in line.get("spans", [])]).strip()
                if line_str:
                    block_lines.append(line_str)

            if not block_lines:
                continue

            full_text = " ".join(block_lines)
            bbox = block["bbox"]

            page_elements.append({
                "element_type": "text",
                "label": "PARAGRAPH",
                "text": full_text,
                "bbox": bbox,
                "top": bbox[1],  # Y-top coordinate for spatial sorting
                "page_no": page_num
            })

        # 3. Sort ALL elements on the page by top Y-coordinate (top-to-bottom reading order)
        page_elements.sort(key=lambda el: (el["top"], el["bbox"][0]))
        return page_elements

    def parse(self):
        text_counter = 0
        line_counter = 0

        for page_idx, page in enumerate(self.doc):
            page_num = page_idx + 1
            elements = self.extract_page_elements(page, page_num)

            last_text_obj = None

            for el in elements:
                # --- CASE A: Vector Answer Line ---
                if el["element_type"] == "vector_line":
                    line_counter += 1
                    line_ref = f"#/blank_lines/{line_counter}"

                    # Check if line sits right below the preceding text block (within 15pt)
                    is_attached_to_text = False
                    if last_text_obj:
                        text_bottom = last_text_obj["prov"][0]["bbox"][3]
                        line_top = el["top"]
                        if 0 <= (line_top - text_bottom) <= 15.0:
                            is_attached_to_text = True

                    line_obj = {
                        "self_ref": line_ref,
                        "label": "ANSWER_LINE",
                        "length": el["length"],
                        "attached_to_above_text": is_attached_to_text,
                        "prov": [{"page_no": page_num, "bbox": el["bbox"]}],
                        "parent": {"cref": last_text_obj["self_ref"] if is_attached_to_text else "#/body"}
                    }

                    self.blank_lines.append(line_obj)
                    self.ref_map[line_ref] = line_obj

                    # Attach to the preceding text node as a child, or directly to body
                    if is_attached_to_text and last_text_obj:
                        if "children" not in last_text_obj:
                            last_text_obj["children"] = []
                        last_text_obj["children"].append({"cref": line_ref})
                    else:
                        self.body["children"].append({"cref": line_ref})

                # --- CASE B: Text Block ---
                else:
                    text_counter += 1
                    text_ref = f"#/texts/{text_counter}"

                    text_obj = {
                        "self_ref": text_ref,
                        "label": "PARAGRAPH",
                        "text": el["text"],
                        "prov": [{"page_no": page_num, "bbox": el["bbox"]}],
                        "parent": {"cref": "#/body"}
                    }

                    self.texts.append(text_obj)
                    self.ref_map[text_ref] = text_obj
                    self.body["children"].append({"cref": text_ref})

                    # Track last text block for line spatial attachment
                    last_text_obj = text_obj

        return self.body, self.ref_map


def print_tree(node, ref_map: dict, prefix: str = "", is_last: bool = True):
    """Recursively prints the unified tree showing text and embedded lines."""
    label = node.get("label", "NODE")
    self_ref = node.get("self_ref", "")
    id_str = f" [{self_ref}]" if self_ref else ""

    extra_info = ""
    if "text" in node:
        clean_text = node["text"].strip().replace("\n", " ")
        if len(clean_text) > 35:
            clean_text = clean_text[:32] + "..."
        extra_info = f' -> "{clean_text}"'
    elif label == "ANSWER_LINE":
        extra_info = f' (Length: {node.get("length")}pt)'

    connector = "└── " if is_last else "├── "
    print(f"{prefix}{connector}[{label}]{id_str}{extra_info}")

    children = node.get("children", [])
    child_prefix = prefix + ("    " if is_last else "│   ")
    count = len(children)

    for idx, child in enumerate(children):
        child_is_last = (idx == count - 1)
        cref = child.get("cref") if isinstance(child, dict) else child
        child_node = ref_map.get(cref)

        if child_node:
            print_tree(child_node, ref_map, prefix=child_prefix, is_last=child_is_last)


# --- Execution Example ---
if __name__ == "__main__":
    parser = SpatiallyIntegratedPDFParser("pdfs/csg.pdf")
    body_root, ref_map = parser.parse()

    print("Spatially Integrated Document Tree (Text + Vector Answer Lines):")
    print("=" * 65)
    print_tree(body_root, ref_map)