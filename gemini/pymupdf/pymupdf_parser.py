import fitz  # PyMuPDF
import json
import os
from pathlib import Path


def rgb_to_hex(color_int):
    """Converts PyMuPDF color integer to Hex string."""
    if color_int is None:
        return "#000000"
    r = (color_int >> 16) & 0xFF
    g = (color_int >> 8) & 0xFF
    b = color_int & 0xFF
    return f"#{r:02x}{g:02x}{b:02x}"


def build_canonical_document(pdf_path: str, output_assets_dir: str = "extracted_assets"):
    os.makedirs(output_assets_dir, exist_ok=True)
    doc = fitz.open(pdf_path)

    canonical_doc = {
        "document_id": Path(pdf_path).stem,
        "filename": os.path.basename(pdf_path),
        "total_pages": len(doc),
        "learning_units": []
    }

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        page_num = page_idx + 1
        page_rect = page.rect

        # 1. Base Learning Unit structure
        unit = {
            "unit_id": f"unit_page_{page_num}",
            "page_number": page_num,
            "page_dimensions": {
                "width": page_rect.width,
                "height": page_rect.height,
                "unit": "pt"
            },
            "typography_manifest": {},
            "elements": []
        }

        # 2. Extract Text, Fonts, Inline Styles, and Bounding Boxes
        # 'rawdict' gives exact font names, sizes, colors, and line coordinates
        page_text_data = page.get_text("rawdict")

        element_counter = 0
        font_catalog = {}

        for block in page_text_data.get("blocks", []):
            if block.get("type") == 0:  # Text block
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        element_counter += 1

                        font_name = span.get("font", "Unknown")
                        font_size = round(span.get("size", 0), 2)
                        font_color = rgb_to_hex(span.get("color"))
                        font_id = f"font_{hash(font_name + str(font_size) + font_color) % 10000}"

                        # Populate typography manifest
                        if font_id not in font_catalog:
                            font_catalog[font_id] = {
                                "font_name": font_name,
                                "size": font_size,
                                "color": font_color,
                                "flags": span.get("flags", 0)  # Contains bold/italic bitflags
                            }

                        bbox = span.get("bbox")  # (x0, y0, x1, y1)

                        unit["elements"].append({
                            "element_id": f"p{page_num}_e{element_counter}",
                            "type": "text_span",
                            "text": span.get("text"),
                            "bbox": {
                                "l": round(bbox[0], 2),
                                "t": round(bbox[1], 2),
                                "r": round(bbox[2], 2),
                                "b": round(bbox[3], 2),
                                "origin": "TOP_LEFT"
                            },
                            "style": {
                                "font_id": font_id,
                                "is_bold": bool(span.get("flags", 0) & 2 ** 4),
                                "is_italic": bool(span.get("flags", 0) & 2 ** 1)
                            }
                        })

        unit["typography_manifest"] = font_catalog

        # 3. Extract Images with exact sizes, dpi, and visual locations
        image_list = page.get_images(full=True)
        for img_idx, img_info in enumerate(image_list):
            xref = img_info[0]
            base_image = doc.extract_image(xref)

            image_bytes = base_image["image"]
            image_ext = base_image["ext"]

            # Save raw image asset
            image_filename = f"page_{page_num}_img_{img_idx + 1}.{image_ext}"
            image_path = os.path.join(output_assets_dir, image_filename)

            with open(image_path, "wb") as f:
                f.write(image_bytes)

            # Locate where this image XObject is drawn on the page
            for img_rect in page.get_image_rects(xref):
                element_counter += 1
                unit["elements"].append({
                    "element_id": f"p{page_num}_e{element_counter}",
                    "type": "image",
                    "bbox": {
                        "l": round(img_rect.x0, 2),
                        "t": round(img_rect.y0, 2),
                        "r": round(img_rect.x1, 2),
                        "b": round(img_rect.y1, 2),
                        "origin": "TOP_LEFT"
                    },
                    "image_metadata": {
                        "pixel_width": base_image["width"],
                        "pixel_height": base_image["height"],
                        "rendered_width_pt": round(img_rect.width, 2),
                        "rendered_height_pt": round(img_rect.height, 2),
                        "format": image_ext,
                        "asset_path": image_path
                    }
                })

        canonical_doc["learning_units"].append(unit)

    return canonical_doc


# --- Execute and Save ---
canonical_data = build_canonical_document("/Users/rajani/PycharmProjects/Scratchpad/pdfs/csg.pdf")

with open("canonical_document.json", "w", encoding="utf-8") as f:
    json.dump(canonical_data, f, indent=2)

print("Canonical document generation complete.")