"""Docling semantic node extraction for hybrid parsing.

The hybrid parser keeps Docling as the semantic authority while PyMuPDF
provides fine-grained text geometry. This module extracts semantic candidates
from the Docling-derived canonical tree so the merge layer can align semantic
nodes to layout lines.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from learning_platform.models.document import (
    DocumentNode,
    Heading,
    ListBlock,
    Paragraph,
    Question,
)


@dataclass(frozen=True)
class SemanticNodeCandidate:
    """A semantic node candidate used for hybrid alignment."""

    node: DocumentNode
    page_number: int
    order: int
    node_type: str
    text: str
    left: float
    top: float
    right: float
    bottom: float
    metadata: dict[str, Any]


@dataclass(frozen=True)
class SemanticExtraction:
    """Collection of semantic candidates extracted from a root tree."""

    candidates: tuple[SemanticNodeCandidate, ...]


class DoclingSemanticExtractor:
    """Extract semantic candidates from a canonical root node."""

    def extract(self, root: DocumentNode) -> SemanticExtraction:
        candidates: list[SemanticNodeCandidate] = []
        self._collect(root, candidates)
        candidates.sort(key=lambda item: (item.page_number, item.order, item.top, item.left))
        return SemanticExtraction(candidates=tuple(candidates))

    def _collect(self, node: DocumentNode, acc: list[SemanticNodeCandidate]) -> None:
        role = str(node.metadata.get("role", ""))
        if role != "document_root":
            node_type = getattr(node.content, "type", "")
            text = self._node_text(node)
            bbox = node.bbox
            acc.append(
                SemanticNodeCandidate(
                    node=node,
                    page_number=max(0, int(node.page)),
                    order=max(0, int(node.seq)),
                    node_type=str(node_type),
                    text=text,
                    left=float(bbox.x),
                    top=float(bbox.y),
                    right=float(bbox.x + bbox.width),
                    bottom=float(bbox.y + bbox.height),
                    metadata=dict(node.metadata),
                )
            )
        for child in node.children:
            self._collect(child, acc)

    @staticmethod
    def _node_text(node: DocumentNode) -> str:
        content = node.content
        if isinstance(content, (Paragraph, Heading, Question)):
            return content.text.plain_text.strip()
        if isinstance(content, ListBlock):
            return " ".join(item.text.plain_text for item in content.items).strip()
        if getattr(content, "type", "") == "table":
            headers = getattr(content, "headers", [])
            return " | ".join(str(header) for header in headers).strip()
        if getattr(content, "type", "") == "equation":
            return str(getattr(content, "latex", "")).strip()
        if getattr(content, "type", "") == "code_block":
            return str(getattr(content, "code", "")).strip()
        if getattr(content, "type", "") == "figure":
            caption = str(getattr(content, "caption_text", "")).strip()
            alt_text = str(getattr(content, "alt_text", "")).strip()
            return f"{caption} {alt_text}".strip()
        return ""
