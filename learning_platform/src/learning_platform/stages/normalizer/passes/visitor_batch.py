"""Batch visitor passes — fuse compatible normalisation rules into fewer scans.

The original pipeline ran nine sequential passes, each allocating a full copy
of the node list.  This module replaces them with three composite passes that
preserve the same ordering constraints while reducing the number of full list
traversals.

Batch composition
-----------------
BatchOne   — HeadingNormalizationPass → ParagraphMergePass → CaptionAssociationPass
             Single forward scan.  Heading fix must precede paragraph merge (so
             split paragraphs are unified before caption matching), which must
             precede caption association (caption heuristic needs clean paragraphs).

BatchTwo   — ListNormalizationPass + TableNormalizationPass
             Single forward scan.  Both are per-node or carry-flush transforms
             with no cross-dependency; they can be applied to each node in the
             same iteration.

BatchThree — HeadingSectionPass → PageGroupingPass → ParentChildRepairPass
               → ReadingOrderPass
             Structural rewiring passes.  Each depends on the output of the
             previous, so they run sequentially inside one composite object
             (still three internal scans, but the tree rebuild / flat_to_tree
             round-trip happens only once at the end via ParentChildRepairPass).
"""

from __future__ import annotations

import re
from collections import defaultdict
from uuid import UUID, uuid4

from learning_platform.models.document import (
    DocumentNode,
    Equation,
    Figure,
    Heading,
    HeadingLevel,
    ListBlock,
    Paragraph,
    StyledText,
    TableBlock,
    TableCell,
    TableRow,
    TextRun,
)

from . import _helpers

# ── Caption pattern (same as CaptionAssociationPass) ─────────────────────────
_CAPTION_PATTERN = re.compile(
    r"^(?:Figure|Fig\.?|Table|Equation|Eq\.?)\s*\d+",
    re.IGNORECASE,
)


# ─────────────────────────────────────────────────────────────────────────────
# Batch 1: Heading fix + Paragraph merge + Caption association
# ─────────────────────────────────────────────────────────────────────────────


class BatchOnePass:
    """Single-scan fusion of heading normalisation, paragraph merge, and caption
    association.

    Execution order within the scan mirrors the original sequential pipeline:
    1. Heading level is corrected as each heading node is visited.
    2. Consecutive paragraphs are accumulated in a carry buffer and flushed
       (merged) on any non-paragraph node.
    3. Caption paragraphs immediately following a Figure or Equation are
       consumed and promoted into that element's caption field.
    """

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        result: list[DocumentNode] = []

        # HeadingNormalizationPass state
        expected_level: int = 0

        # ParagraphMergePass state
        para_carry: DocumentNode | None = None

        # CaptionAssociationPass state
        prev_captionable: DocumentNode | None = None  # last Figure or Equation in result

        def flush_para() -> DocumentNode | None:
            """Return the accumulated paragraph carry and reset it."""
            nonlocal para_carry
            node = para_carry
            para_carry = None
            return node

        def emit(node: DocumentNode) -> None:
            """Append a fully-processed node to result, updating caption state."""
            nonlocal prev_captionable
            result.append(node)
            if isinstance(node.content, (Figure, Equation)):
                prev_captionable = node
            elif _helpers.is_heading(node):
                # A heading between a figure and its caption breaks association.
                prev_captionable = None
            else:
                prev_captionable = None

        for node in nodes:
            # ── Step 1: fix heading levels ────────────────────────────────────
            if _helpers.is_heading(node):
                # Flush any accumulated paragraph before emitting a heading.
                if para_carry is not None:
                    emit(flush_para())  # type: ignore[arg-type]
                    prev_captionable = None  # heading after para breaks caption

                current_level = int(node.content.level)
                if expected_level == 0:
                    current_level = 1
                if current_level > expected_level + 1:
                    current_level = expected_level + 1

                if current_level != int(node.content.level):
                    safe_level = min(current_level, 4)
                    new_content = Heading(
                        level=HeadingLevel(safe_level),
                        text=node.content.text,
                        metadata=node.content.metadata,
                    )
                    node = node.model_copy(update={"content": new_content, "level": safe_level})

                expected_level = int(node.content.level)
                emit(node)
                continue

            # ── Step 2: paragraph carry / merge ──────────────────────────────
            if _helpers.is_paragraph(node):
                # Check caption heuristic first.
                is_caption = _CAPTION_PATTERN.match(_helpers.plain_text(node)) is not None

                if is_caption and prev_captionable is not None and para_carry is None:
                    # Absorb as caption — flush carry is empty by guard above.
                    caption_text = _helpers.plain_text(node)
                    content = prev_captionable.content

                    if isinstance(content, Figure):
                        new_content = Figure(
                            caption_text=caption_text,
                            image_uri=content.image_uri,
                            alt_text=content.alt_text,
                            caption_node_id=content.caption_node_id,
                            width=content.width,
                            height=content.height,
                            format=content.format,
                            mimetype=content.mimetype,
                            storage_key=content.storage_key,
                            size_bytes=content.size_bytes,
                            metadata=content.metadata,
                        )
                        updated = prev_captionable.model_copy(update={"content": new_content})
                        result[-1] = updated
                        prev_captionable = updated
                        continue

                    if isinstance(content, Equation):
                        new_content = Equation(
                            latex=content.latex,
                            mathml=content.mathml,
                            label=content.label,
                            is_block=content.is_block,
                            metadata={**content.metadata, "caption": caption_text},
                        )
                        updated = prev_captionable.model_copy(update={"content": new_content})
                        result[-1] = updated
                        prev_captionable = updated
                        continue

                # Ordinary paragraph — accumulate in carry.
                if para_carry is None:
                    para_carry = node
                else:
                    prev_text = _helpers.plain_text(para_carry)
                    curr_text = _helpers.plain_text(node)
                    merged_text = f"{prev_text} {curr_text}".strip()
                    new_content = Paragraph(
                        text=StyledText(runs=[TextRun(text=merged_text)]),
                        metadata=para_carry.content.metadata,
                    )
                    para_carry = para_carry.model_copy(update={"content": new_content})
                continue

            # ── Non-paragraph, non-heading: flush carry then emit ─────────────
            if para_carry is not None:
                emit(flush_para())  # type: ignore[arg-type]

            emit(node)

        # Final flush of any trailing paragraph carry.
        if para_carry is not None:
            emit(para_carry)

        return result


# ─────────────────────────────────────────────────────────────────────────────
# Batch 2: List merge + Table normalisation
# ─────────────────────────────────────────────────────────────────────────────


class BatchTwoPass:
    """Single-scan fusion of list normalisation and table normalisation.

    Both transforms are independent: the list carry only interacts with
    consecutive ``ListBlock`` nodes, while the table transform is a pure
    per-node rewrite.  They are applied in one forward scan.
    """

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        result: list[DocumentNode] = []
        carry: DocumentNode | None = None  # ListNormalizationPass carry

        for node in nodes:
            # ── Table normalisation (pure per-node) ───────────────────────────
            if isinstance(node.content, TableBlock):
                if carry is not None:
                    result.append(carry)
                    carry = None
                result.append(self._normalize_table(node))
                continue

            # ── List carry / merge ────────────────────────────────────────────
            if isinstance(node.content, ListBlock):
                if carry is None:
                    carry = node
                    continue

                # Preserve parent-child relationship — don't merge nested lists.
                if node.parent_id == carry.id or carry.parent_id == node.id:
                    result.append(carry)
                    carry = node
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
                    merged_children = list(carry.children) + list(node.children)
                    carry = carry.model_copy(
                        update={"content": new_content, "children": merged_children}
                    )
                else:
                    result.append(carry)
                    carry = node
                continue

            # ── Anything else: flush carry ────────────────────────────────────
            if carry is not None:
                result.append(carry)
                carry = None
            result.append(node)

        if carry is not None:
            result.append(carry)

        return result

    # ── Table helpers (extracted from TableNormalizationPass) ─────────────────

    def _normalize_table(self, node: DocumentNode) -> DocumentNode:
        content = node.content
        assert isinstance(content, TableBlock)
        rows = self._normalize_rows(content.rows)
        headers = content.headers or self._extract_headers(rows)
        col_count = max((len(r.cells) for r in rows), default=0)
        row_count = len(rows)
        new_content = TableBlock(
            rows=rows,
            headers=headers,
            caption=content.caption,
            column_count=col_count,
            row_count=row_count,
            metadata=content.metadata,
        )
        return node.model_copy(update={"content": new_content})

    @staticmethod
    def _normalize_rows(rows: list[TableRow]) -> list[TableRow]:
        normalized: list[TableRow] = []
        for i, row in enumerate(rows):
            cells = row.cells or [TableCell(content=[TextRun(text="")])]
            is_header = row.is_header or (i == 0 and len(rows) > 1)
            normalized.append(TableRow(cells=cells, is_header=is_header, metadata=row.metadata))
        return normalized

    @staticmethod
    def _extract_headers(rows: list[TableRow]) -> list[str]:
        if not rows:
            return []
        return ["".join(run.text for run in cell.content) for cell in rows[0].cells]


# ─────────────────────────────────────────────────────────────────────────────
# Batch 3: Section hierarchy + Page grouping + Repair + Reading order
# ─────────────────────────────────────────────────────────────────────────────


class BatchThreePass:
    """Composite structural-rewiring pass.

    Applies the four passes that must run in strict order and depend on each
    other's output:

    1. ``HeadingSectionPass``  — assign ``parent_id`` from heading hierarchy.
    2. ``PageGroupingPass``    — create page containers, reparent content.
    3. ``ParentChildRepairPass`` — cycle detection, dangling ref repair,
       tree rebuild (single ``flat_to_tree`` / ``tree_to_flat`` round-trip).
    4. ``ReadingOrderPass``    — stable sort on (page, y, x, seq).

    The ``flat_to_tree`` / ``tree_to_flat`` round-trip that was previously
    duplicated inside ``ParentChildRepairPass`` is the only one that occurs;
    the intermediate passes work directly on the flat list.
    """

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        if not nodes:
            return nodes

        nodes = self._heading_section(nodes)
        nodes = self._page_grouping(nodes)
        nodes = self._parent_child_repair(nodes)
        nodes = self._reading_order(nodes)
        return nodes

    # ── HeadingSectionPass logic ──────────────────────────────────────────────

    @staticmethod
    def _heading_section(nodes: list[DocumentNode]) -> list[DocumentNode]:
        valid_ids: set[UUID] = {n.id for n in nodes}
        section_stack: list[tuple[int, UUID]] = []
        result: list[DocumentNode] = []

        for node in nodes:
            if node.metadata.get("role") == "page_group":
                result.append(node)
                continue

            if node.parent_id is not None and node.parent_id not in valid_ids:
                node = node.model_copy(update={"parent_id": None})

            if _helpers.is_heading(node):
                level = _helpers.heading_level(node)
                if not section_stack and level > 1:
                    level = 1
                while section_stack and section_stack[-1][0] >= level:
                    section_stack.pop()
                if section_stack and node.parent_id is None:
                    node = node.model_copy(update={"parent_id": section_stack[-1][1]})
                section_stack.append((level, node.id))
            else:
                if section_stack and node.parent_id is None:
                    node = node.model_copy(update={"parent_id": section_stack[-1][1]})

            result.append(node)

        return result

    # ── PageGroupingPass logic ────────────────────────────────────────────────

    @staticmethod
    def _page_grouping(nodes: list[DocumentNode]) -> list[DocumentNode]:
        page_buckets: dict[int, list[DocumentNode]] = defaultdict(list)
        node_map: dict[str, DocumentNode] = {}

        for node in nodes:
            page_num = node.page if node.page > 0 else 0
            page_buckets[page_num].append(node)
            node_map[str(node.id)] = node

        page_containers: dict[int, DocumentNode] = {}
        for page_num in sorted(page_buckets.keys()):
            if page_num == 0:
                continue
            container = DocumentNode(
                id=uuid4(),
                content=Paragraph(text=StyledText(runs=[TextRun(text="")])),
                metadata={"role": "page_group", "page_number": page_num},
                page=page_num,
            )
            page_containers[page_num] = container

        result: list[DocumentNode] = []
        for page_num in sorted(page_buckets.keys()):
            page_nodes = page_buckets[page_num]
            if page_num == 0:
                result.extend(page_nodes)
                continue

            container = page_containers[page_num]
            result.append(container)

            for node in page_nodes:
                if node.parent_id is not None and str(node.parent_id) in node_map:
                    result.append(node)
                    continue
                node.parent_id = container.id
                result.append(node)

        return result

    # ── ParentChildRepairPass logic ───────────────────────────────────────────

    @staticmethod
    def _parent_child_repair(nodes: list[DocumentNode]) -> list[DocumentNode]:
        # Collect all descendants (including pre-existing embedded children).
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

        by_id: dict[UUID, DocumentNode] = {n.id: n for n in result}

        # Cycle detection via DFS.
        visiting: set[UUID] = set()
        visited: set[UUID] = set()

        def dfs(node_id: UUID) -> None:
            if node_id in visiting:
                n = by_id.get(node_id)
                if n is not None:
                    by_id[node_id] = n.model_copy(update={"parent_id": None})
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            n = by_id.get(node_id)
            if n is not None and n.parent_id is not None:
                dfs(n.parent_id)
            visiting.discard(node_id)
            visited.add(node_id)

        for nid in list(by_id.keys()):
            if nid not in visited:
                dfs(nid)

        # Repair dangling parent_id references.
        for nid, n in list(by_id.items()):
            if n.parent_id is not None and n.parent_id not in by_id:
                by_id[nid] = n.model_copy(update={"parent_id": None})

        # Single flat_to_tree / tree_to_flat round-trip.
        root = _helpers.flat_to_tree(list(by_id.values()))
        return _helpers.tree_to_flat(root)

    # ── ReadingOrderPass logic ────────────────────────────────────────────────

    @staticmethod
    def _reading_order(nodes: list[DocumentNode]) -> list[DocumentNode]:
        indexed = list(enumerate(nodes))
        indexed.sort(
            key=lambda pair: (
                pair[1].page,
                pair[1].bbox.y,
                pair[1].bbox.x,
                pair[1].seq,
                pair[0],
            )
        )
        return [node for _, node in indexed]
