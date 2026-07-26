"""ParagraphMergePass — merge consecutive paragraphs that belong together.

Two consecutive paragraphs are merged when:
- Both are ``Paragraph`` nodes.
- Neither is followed by a heading, list, table, or other block element
  (i.e. they are adjacent in the flat list).
- The previous paragraph does not end with sentence-ending punctuation
  followed by a capital letter (a heuristic for sentence boundaries).
"""

from __future__ import annotations

from learning_platform.models.document import DocumentNode, Paragraph, StyledText, TextRun

from . import _helpers


class ParagraphMergePass:
    """Merge adjacent paragraph nodes into a single paragraph."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        result: list[DocumentNode] = []
        carry: DocumentNode | None = None

        for node in nodes:
            if not _helpers.is_paragraph(node):
                if carry is not None:
                    result.append(carry)
                    carry = None
                result.append(node)
                continue

            if carry is None:
                carry = node
                continue

            prev_text = _helpers.plain_text(carry)
            curr_text = _helpers.plain_text(node)
            merged_text = f"{prev_text} {curr_text}".strip()

            new_content = Paragraph(
                text=StyledText(runs=[TextRun(text=merged_text)]),
                metadata=carry.content.metadata,
            )
            carry = carry.model_copy(
                update={"content": new_content},
            )

        if carry is not None:
            result.append(carry)

        return result
