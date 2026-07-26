"""HeadingSectionPass — establish section hierarchy from heading levels.

This pass is a fallback for documents that don't have Docling's tree
structure. It uses heading levels and reading order to create parent-child
relationships.

For Docling-parsed documents, this pass only fixes broken relationships
and doesn't recreate hierarchy from scratch.

Rules:
- The first heading encountered is anchored at level 1.
- A heading's parent is the most recent heading with a strictly lower level.
- Content after a heading (until the next heading at same or higher level)
  becomes a child of that heading.
- Content before any heading remains at root level (no parent assigned).
- Nodes that already have a valid ``parent_id`` are left unchanged.
"""

from __future__ import annotations

from uuid import UUID

from learning_platform.models.document import DocumentNode

from . import _helpers


class HeadingSectionPass:
    """Create section hierarchy from heading levels.

    Walks the flat node list in reading order and sets ``parent_id``
    on each node to establish a heading-driven section tree.
    """

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        # Build a set of all valid node IDs for parent validation
        valid_ids: set[UUID] = {n.id for n in nodes}

        # Stack of (level, node_id) for open sections.
        section_stack: list[tuple[int, UUID]] = []
        result: list[DocumentNode] = []

        for node in nodes:
            # Skip page container nodes - they handle their own hierarchy
            if node.metadata.get("role") == "page_group":
                result.append(node)
                continue

            # Validate existing parent_id
            if node.parent_id is not None and node.parent_id not in valid_ids:
                node = node.model_copy(update={"parent_id": None})

            if _helpers.is_heading(node):
                level = _helpers.heading_level(node)

                # Anchor the first heading at level 1 if it's higher.
                if not section_stack and level > 1:
                    level = 1

                # Pop sections at the same or deeper level.
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()

                # Parent is the current section head, if one exists.
                if section_stack and node.parent_id is None:
                    node = node.model_copy(update={"parent_id": section_stack[-1][1]})

                section_stack.append((level, node.id))
            else:
                # Non-heading content becomes a child of the current section.
                if section_stack and node.parent_id is None:
                    node = node.model_copy(update={"parent_id": section_stack[-1][1]})

            result.append(node)

        return result
