import fitz  # PyMuPDF
import re
from typing import List, Dict, Any, Optional
from collections import Counter


class AdvancedPDFParserWithLineDetection:
    def __init__(self, pdf_path: str):
        self.pdf_path = pdf_path
        self.doc = fitz.open(pdf_path)

        self.texts: List[Dict[str, Any]] = []
        self.blank_lines: List[Dict[str, Any]] = []  # Detected blanks/lines
        self.ref_map: Dict[str, Any] = {}

        self.body = {"self_ref": "#/body", "label": "BODY", "children": []}
        self.ref_map["#/body"] = self.body

    def detect_vector_lines(self, page: fitz.Page, page_num: int) -> List[Dict[str, Any]]:
        """Extracts drawn horizontal vector lines (e.g., answer lines, underline blanks)."""
        detected_lines = []
        drawings = page.get_drawings()

        for path in drawings:
            # We look for lines or thin rectangles
            for item in path.get("items", []):
                if item[0] == "l":  # Line command: ('l', p1, p2)
                    p1, p2 = item[1], item[2]

                    # Check if line is horizontal (y1 roughly equals y2)
                    is_horizontal = abs(p1.y - p2.y) < 2.0
                    length = abs(p1.x - p2.x)

                    # Filter: Horizontal line with reasonable length (e.g., > 20 points wide)
                    if is_horizontal and length >= 20.0:
                        bbox = [min(p1.x, p2.x), min(p1.y, p2.y) - 2, max(p1.x, p2.x), max(p1.y, p2.y) + 2]
                        detected_lines.append({
                            "type": "vector_line",
                            "bbox": bbox,
                            "length": round(length, 2),
                            "page_no": page_num
                        })

        return detected_lines

    def parse(self):
        text_counter = 0
        line_counter = 0

        # Regex for text-based fill-in-the-blanks: 2 or more consecutive underscores, dots, or dashes
        text_line_pattern = re.compile(r'(__{2,}|–{2,}|-{3,}|\.{4,})')

        for page_idx, page in enumerate(self.doc):
            page_num = page_idx + 1

            # --- STEP A: Detect Drawn Vector Lines ---
            vector_lines = self.detect_vector_lines(page, page_num)
            for v_line in vector_lines:
                line_counter += 1
                line_ref = f"#/blank_lines/{line_counter}"

                line_obj = {
                    "self_ref": line_ref,
                    "label": "ANSWER_LINE_VECTOR",
                    "bbox": v_line["bbox"],
                    "length": v_line["length"],
                    "prov": [{"page_no": page_num}]
                }
                self.blank_lines.append(line_obj)
                self.ref_map[line_ref] = line_obj

            # --- STEP B: Detect Text & Text-based Fill-in-the-blanks ---
            text_page = page.get_text("dict")

            for block in text_page.get("blocks", []):
                if block.get("type") != 0:
                    continue

                full_text = ""
                for line in block.get("lines", []):
                    line_str = "".join([span["text"] for span in line.get("spans", [])]).strip()
                    if line_str:
                        full_text += " " + line_str

                full_text = full_text.strip()
                if not full_text:
                    continue

                # Check if text contains underscore/dash fill-in-the-blank patterns
                has_text_blank = bool(text_line_pattern.search(full_text))

                text_ref = f"#/texts/{text_counter}"
                text_counter += 1

                label = "PARAGRAPH"
                if has_text_blank:
                    label = "FILL_IN_THE_BLANK_TEXT"

                text_obj = {
                    "self_ref": text_ref,
                    "label": label,
                    "text": full_text,
                    "has_blank_line": has_text_blank,
                    "prov": [{"page_no": page_num, "bbox": block["bbox"]}],
                    "parent": {"cref": "#/body"}
                }

                self.texts.append(text_obj)
                self.ref_map[text_ref] = text_obj
                self.body["children"].append({"cref": text_ref})

        return self.body, self.ref_map


# --- Execution ---
if __name__ == "__main__":
    parser = AdvancedPDFParserWithLineDetection("pdfs/csg.pdf")
    body_root, ref_map = parser.parse()

    print(f"Total Text Blocks: {len(parser.texts)}")
    print(f"Total Vector Lines Found: {len(parser.blank_lines)}")
    print("=" * 60)

    # Print Detected Fill-in-the-Blanks
    for text_item in parser.texts:
        if text_item.get("has_blank_line"):
            print(f"[{text_item['label']}] -> {text_item['text']}")

    for line_item in parser.blank_lines:
        print(f"[{line_item['label']}] Length: {line_item['length']}pt | BBox: {line_item['bbox']}")