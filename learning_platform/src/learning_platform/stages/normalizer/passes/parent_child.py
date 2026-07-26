"""ParentChildRepairPass — rebuild the parent-child tree from a flat list.

This pass reconstructs the document tree and validates:

- Every non-root node has a valid ``parent_id`` (or is promoted to root).
- No cycles exist in the parent-child graph.
- Children of each node are in reading order.
- ``parent_id`` references are consistent with the tree structure.

The repaired tree is flattened back into a pre-order list.
"""

from __future__ import annotations

from uuid import UUID

from learning_platform.models.document import (
    DocumentNode,
)

from . import _helpers


class ParentChildRepairPass:
    """Rebuild and validate the parent-child tree structure."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        all_nodes = self._collect_all_descendants(nodes)
        by_id: dict[UUID, DocumentNode] = {n.id: n for n in all_nodes}

        self._remove_cycles(by_id)
        self._repair_parent_ids(by_id)

        root = _helpers.flat_to_tree(list(by_id.values()))
        return _helpers.tree_to_flat(root)

    @staticmethod
    def _collect_all_descendants(nodes: list[DocumentNode]) -> list[DocumentNode]:
        """Flatten the node list, including any pre-existing embedded children."""
        result: list[DocumentNode] = []
        stack: list[DocumentNode] = list(nodes)
        seen: set[UUID] = set()
        while stack:
            node = stack.pop()
            if node.id in seen:
                continue
            seen.add(node.id)
            result.append(node)
            stack.extend(node.children)
        return result

    def _remove_cycles(self, by_id: dict[UUID, DocumentNode]) -> None:
        """Detect and break cycles by clearing ``parent_id`` on the back-edge."""
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        for node_id in list(by_id.keys()):
            if node_id not in visited:
                self._dfs_cycle_check(node_id, by_id, visiting, visited)

    def _dfs_cycle_check(
        self,
        node_id: UUID,
        by_id: dict[UUID, DocumentNode],
        visiting: set[UUID],
        visited: set[UUID],
    ) -> None:
        """Depth-first cycle detection. Breaks back-edges by clearing ``parent_id``."""
        if node_id in visiting:
            node = by_id.get(node_id)
            if node is not None:
                by_id[node_id] = node.model_copy(update={"parent_id": None})
            return
        if node_id in visited:
            return

        visiting.add(node_id)
        node = by_id.get(node_id)
        if node is not None and node.parent_id is not None:
            self._dfs_cycle_check(node.parent_id, by_id, visiting, visited)
        visiting.discard(node_id)
        visited.add(node_id)

    def _repair_parent_ids(self, by_id: dict[UUID, DocumentNode]) -> None:
        """Ensure every ``parent_id`` points to an existing node."""
        for node_id, node in list(by_id.items()):
            if node.parent_id is not None and node.parent_id not in by_id:
                by_id[node_id] = node.model_copy(update={"parent_id": None})

    def _attach_children(self, by_id: dict[UUID, DocumentNode]) -> None:
        """Rebuild ``children`` lists from ``parent_id`` references."""
        for node in by_id.values():
            node.children.clear()

        for node in by_id.values():
            if node.parent_id is not None and node.parent_id in by_id:
                parent = by_id[node.parent_id]
                parent.children.append(node)
