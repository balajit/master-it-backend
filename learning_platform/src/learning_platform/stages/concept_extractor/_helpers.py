"""Shared helpers for concept extraction strategies."""

from __future__ import annotations

import re
from collections import Counter

from learning_platform.models.annotation import (
    Annotation,
    DefinitionAnnotation,
    KeyTermAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.concept import Concept, ConceptCategory
from learning_platform.models.document import CanonicalDocument, DocumentNode


def plain_text(node: DocumentNode) -> str:
    """Extract plain text from any content block."""
    from learning_platform.models.document import (
        Callout,
        CodeBlock,
        Definition,
        Equation,
        Exercise,
        Figure,
        Heading,
        ListBlock,
        Note,
        Paragraph,
        Reference,
        TableBlock,
    )

    content = node.content
    if isinstance(content, (Paragraph, Heading)):
        return content.text.plain_text
    if isinstance(content, ListBlock):
        return "\n".join(item.text.plain_text for item in content.items)
    if isinstance(content, (Note, Callout)):
        return content.text.plain_text
    if isinstance(content, CodeBlock):
        return content.code
    if isinstance(content, TableBlock):
        return " | ".join(content.headers) if content.headers else ""
    if isinstance(content, Figure):
        return content.alt_text or content.caption_text
    if isinstance(content, Equation):
        return content.latex
    if isinstance(content, Exercise):
        return content.question.plain_text
    if isinstance(content, Definition):
        return f"{content.term}: {content.definition}"
    if isinstance(content, Reference):
        return content.text
    return ""


def all_text(document: CanonicalDocument) -> str:
    """Concatenate plain text from all nodes in the document."""
    return "\n".join(plain_text(n) for n in document.nodes if plain_text(n))


def count_mentions(text: str, name: str, aliases: list[str]) -> int:
    """Count how many times a concept name or its aliases appear in *text*."""
    counter: Counter[str] = Counter()
    combined = [name] + aliases
    lower_text = text.lower()
    for term in combined:
        pattern = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
        counter[term] += len(pattern.findall(lower_text))
    return sum(counter.values())


def find_mentions(text: str, name: str, aliases: list[str]) -> list[re.Match[str]]:
    """Return all regex matches for a concept name or aliases in *text*."""
    combined = [name] + aliases
    lower_text = text.lower()
    matches: list[re.Match[str]] = []
    for term in combined:
        pattern = re.compile(r"\b" + re.escape(term.lower()) + r"\b")
        matches.extend(pattern.finditer(lower_text))
    return matches


def concepts_from_annotations(
    annotations: list[Annotation],
) -> list[Concept]:
    """Derive initial concepts from enrichment annotations."""
    concepts: list[Concept] = []
    seen: dict[str, Concept] = {}

    for ann in annotations:
        if isinstance(ann, DefinitionAnnotation) and ann.term:
            name = ann.term.strip()
            key = name.lower()
            if key in seen:
                seen[key].mention_count += 1
                if ann.node_id not in seen[key].source_node_ids:
                    seen[key].source_node_ids.append(ann.node_id)
            else:
                c = Concept(
                    name=name,
                    category=ConceptCategory.DEFINITION,
                    aliases=[],
                    importance=ann.confidence,
                    mention_count=1,
                    source_node_ids=[ann.node_id],
                )
                seen[key] = c
                concepts.append(c)

        elif isinstance(ann, KeyTermAnnotation) and ann.term:
            name = ann.term.strip()
            key = name.lower()
            if key in seen:
                seen[key].mention_count += 1
                if ann.node_id not in seen[key].source_node_ids:
                    seen[key].source_node_ids.append(ann.node_id)
            else:
                c = Concept(
                    name=name,
                    category=ConceptCategory.VOCABULARY,
                    aliases=[],
                    importance=ann.confidence,
                    mention_count=1,
                    source_node_ids=[ann.node_id],
                )
                seen[key] = c
                concepts.append(c)

        elif isinstance(ann, ObjectiveAnnotation) and ann.objective_text:
            text = ann.objective_text.strip()
            c = Concept(
                name=text[:120],
                category=ConceptCategory.SKILL,
                aliases=[],
                importance=ann.confidence * 0.8,
                mention_count=1,
                source_node_ids=[ann.node_id],
            )
            concepts.append(c)

    return concepts
