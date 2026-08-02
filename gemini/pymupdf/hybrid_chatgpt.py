#!/usr/bin/env python3

"""
Extract typography from PDFs by combining:

    - Docling (document structure)
    - PyMuPDF rawdict (font metadata)
    - IoU bbox matching
    - RapidFuzz text verification

Author: ChatGPT
"""

import sys
import re
from dataclasses import dataclass
from typing import List

import fitz
from rapidfuzz import fuzz

from docling.document_converter import DocumentConverter


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------

IOU_THRESHOLD = 0.25
TEXT_MATCH_THRESHOLD = 90

# ----------------------------------------------------------------------
# Models
# ----------------------------------------------------------------------

@dataclass
class FontSpan:
    page: int
    text: str
    bbox: fitz.Rect
    font: str
    size: float
    flags: int
    color: int


# ----------------------------------------------------------------------
# Utility functions
# ----------------------------------------------------------------------

def normalize(text: str) -> str:
    """Normalize whitespace."""
    return re.sub(r"\s+", " ", text).strip()


def rect_from_docling_bbox(bbox):
    """
    Convert Docling bbox to PyMuPDF Rect.
    """
    return fitz.Rect(
        bbox.l,
        bbox.t,
        bbox.r,
        bbox.b
    )


def iou(rect1: fitz.Rect, rect2: fitz.Rect) -> float:
    """
    Compute Intersection over Union.
    """

    print(f' rect1: {rect1} - rect2: {rect2}')
    inter = rect1 & rect2

    if inter.is_empty:
        return 0.0

    inter_area = inter.get_area()

    union = (
        rect1.get_area()
        + rect2.get_area()
        - inter_area
    )

    if union == 0:
        return 0.0

    return inter_area / union


# ----------------------------------------------------------------------
# Extract raw PDF spans
# ----------------------------------------------------------------------

def extract_pdf_spans(pdf_path: str) -> List[FontSpan]:

    pdf = fitz.open(pdf_path)

    spans = []

    for page_index, page in enumerate(pdf):

        raw = page.get_text("rawdict")

        for block in raw["blocks"]:

            if block["type"] != 0:
                continue

            for line in block["lines"]:

                for span in line["spans"]:

                    chars = span.get("chars", [])

                    if chars:
                        text = "".join(c["c"] for c in chars)
                    else:
                        text = span.get("text", "")

                    spans.append(
                        FontSpan(
                            page=page_index + 1,
                            text=text,
                            bbox=fitz.Rect(span["bbox"]),
                            font=span["font"],
                            size=span["size"],
                            flags=span["flags"],
                            color=span["color"]
                        )
                    )

    pdf.close()

    return spans


# ----------------------------------------------------------------------
# Docling
# ----------------------------------------------------------------------

def extract_docling(pdf_path):

    converter = DocumentConverter()

    result = converter.convert(pdf_path)

    return result.document


# ----------------------------------------------------------------------
# Matching
# ----------------------------------------------------------------------

def collect_candidates(doc_item, spans):

    candidates = []

    if not hasattr(doc_item, "prov"):
        return candidates

    for prov in doc_item.prov:

        page = prov.page_no

        doc_rect = rect_from_docling_bbox(prov.bbox)

        for span in spans:

            if span.page != page:
                continue

            overlap = iou(doc_rect, span.bbox)

            if overlap >= IOU_THRESHOLD:

                candidates.append(
                    (
                        overlap,
                        span
                    )
                )

    candidates.sort(
        key=lambda x: (
            x[1].bbox.y0,
            x[1].bbox.x0
        )
    )

    return candidates


def verify_text(doc_text, candidate_spans):

    pdf_text = normalize(
        "".join(
            span.text
            for _, span in candidate_spans
        )
    )

    doc_text = normalize(doc_text)

    score = fuzz.ratio(
        doc_text,
        pdf_text
    )

    return score, pdf_text


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

def process(pdf_path):

    print("Loading Docling...")
    doc = extract_docling(pdf_path)

    print("Reading PDF typography...")
    spans = extract_pdf_spans(pdf_path)

    print()

    for item, _ in doc.iterate_items():

        if not hasattr(item, "text"):
            continue

        doc_text = normalize(item.text)

        if not doc_text:
            continue

        candidates = collect_candidates(item, spans)

        if not candidates:
            continue

        score, reconstructed = verify_text(
            doc_text,
            candidates
        )

        if score < TEXT_MATCH_THRESHOLD:
            continue

        print("=" * 90)
        print(doc_text)
        print()

        print(f"Similarity : {score:.1f}%")

        if hasattr(item, "prov"):

            p = item.prov[0]

            print(f"Page       : {p.page_no}")
            print(f"BBox       : {p.bbox}")

        print()

        print("Typography")

        for overlap, span in candidates:

            print(
                f"'{span.text}'\n"
                f"    font   : {span.font}\n"
                f"    size   : {span.size:.2f}\n"
                f"    flags  : {span.flags}\n"
                f"    color  : {span.color}\n"
                f"    IoU    : {overlap:.3f}"
            )

        print()

        print("Reconstructed:")
        print(reconstructed)

        print()


# ----------------------------------------------------------------------

if __name__ == "__main__":

    if len(sys.argv) != 2:
       pdf_path = "/Users/rajani/PycharmProjects/Scratchpad/pdfs/csg.pdf"
    else:
        pdf_path = sys.argv[1]


    process(pdf_path)