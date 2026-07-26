"""Shared helpers for enrichment detectors."""

from __future__ import annotations

import re

from learning_platform.models.document import CanonicalDocument, DocumentNode, StyledText


def plain_text(node: DocumentNode) -> str:
    """Extract the plain-text content of a node, regardless of its type."""
    content = node.content
    if hasattr(content, "text") and isinstance(content.text, StyledText):
        return content.text.plain_text
    if hasattr(content, "question") and isinstance(content.question, StyledText):
        return content.question.plain_text
    return ""


def text_nodes(document: CanonicalDocument) -> list[DocumentNode]:
    """Return all nodes that carry text content (Paragraph, Heading, Note, etc.)."""
    from learning_platform.models.document import Heading, Note, Paragraph

    return [n for n in document.nodes if isinstance(n.content, (Paragraph, Heading, Note))]


def find_pattern(
    document: CanonicalDocument,
    pattern: re.Pattern[str],
) -> list[tuple[DocumentNode, re.Match[str]]]:
    """Return ``(node, match)`` pairs for every regex hit across text nodes."""
    results: list[tuple[DocumentNode, re.Match[str]]] = []
    for node in text_nodes(document):
        text = plain_text(node)
        for match in pattern.finditer(text):
            results.append((node, match))
    return results
