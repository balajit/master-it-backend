"""PageGroupingPass — create page container nodes for document structure.

This pass groups all nodes by their page number and creates synthetic
*page container* nodes that hold all content for each page. The page
container becomes the parent of all nodes on that page.

Page container nodes carry ``metadata["role"] = "page_group"]`` and
``metadata["page_number"]`` so that downstream passes can identify them.

Rules:
- Each page with content gets a page container node.
- All nodes on a page become children of that page's container.
- Nodes that already have a ``parent_id`` within the same page are
  left unchanged (preserving Docling's tree structure).
- Nodes with ``parent_id`` pointing to a node on a different page
  are reparented to the page container.
- Page containers are ordered by page number.
"""

from __future__ import annotations

from collections import defaultdict
from uuid import uuid4

from learning_platform.models.document import (
    DocumentNode,
    Paragraph,
    StyledText,
    TextRun,
)


class PageGroupingPass:
    """Create page container nodes and group content by page."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        # Step 1: Collect all nodes and their page numbers
        page_buckets: dict[int, list[DocumentNode]] = defaultdict(list)
        node_map: dict[str, DocumentNode] = {}

        for node in nodes:
            page_num = node.page if node.page > 0 else 0
            page_buckets[page_num].append(node)
            node_map[str(node.id)] = node

        # Step 2: Create page container nodes
        page_containers: dict[int, DocumentNode] = {}

        for page_num in sorted(page_buckets.keys()):
            if page_num == 0:
                continue  # Skip nodes with unknown page

            container = DocumentNode(
                id=uuid4(),
                content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
                metadata={"role": "page_group", "page_number": page_num},
                page=page_num,
            )
            page_containers[page_num] = container

        # Step 3: Assign nodes to page containers
        result: list[DocumentNode] = []

        for page_num in sorted(page_buckets.keys()):
            page_nodes = page_buckets[page_num]

            if page_num == 0:
                # Nodes with unknown page stay at root level
                result.extend(page_nodes)
                continue

            container = page_containers[page_num]
            result.append(container)

            for node in page_nodes:
                # Preserve parent-child when parent exists in the flat list
                # (even if parent is on a different page, e.g. list groups
                # on page 0 whose items span multiple pages)
                if node.parent_id is not None:
                    parent_str = str(node.parent_id)
                    if parent_str in node_map:
                        result.append(node)
                        continue

                # Reparent to page container
                node.parent_id = container.id
                result.append(node)

        return result
