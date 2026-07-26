"""ListNormalizationPass — merge consecutive list blocks of the same style.

When two ``ListBlock`` nodes appear consecutively and share the same
``ListStyle``, their items are merged into a single list block.
"""

from __future__ import annotations

from learning_platform.models.document import DocumentNode, ListBlock


class ListNormalizationPass:
    """Merge consecutive list blocks that share the same style."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        result: list[DocumentNode] = []
        carry: DocumentNode | None = None

        for node in nodes:
            is_list = isinstance(node.content, ListBlock)

            if not is_list:
                if carry is not None:
                    result.append(carry)
                    carry = None
                result.append(node)
                continue

            if carry is None:
                carry = node
                continue

            # Skip merging if nodes have a parent-child relationship
            if node.parent_id == carry.id or carry.parent_id == node.id:
                if carry is not None:
                    result.append(carry)
                    carry = None
                result.append(node)
                continue

            prev_content = carry.content
            curr_content = node.content

            if prev_content.style == curr_content.style:
                merged_items = prev_content.items + curr_content.items
                new_content = ListBlock(
                    style=prev_content.style,
                    items=merged_items,
                    metadata={**prev_content.metadata, **curr_content.metadata},
                )
                # Preserve children from both nodes (nested sub-lists)
                merged_children = list(carry.children) + list(node.children)
                carry = carry.model_copy(
                    update={"content": new_content, "children": merged_children},
                )
            else:
                result.append(carry)
                carry = node

        if carry is not None:
            result.append(carry)

        return result
