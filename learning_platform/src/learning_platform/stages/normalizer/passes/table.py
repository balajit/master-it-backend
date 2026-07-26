"""TableNormalizationPass — ensure consistent table structure.

Rules:
- Every table must have at least a header row (``is_header=True``).
- ``column_count`` and ``row_count`` are recomputed from actual data.
- Empty cells are filled with empty ``TextRun`` instances.
"""

from __future__ import annotations

from learning_platform.models.document import (
    DocumentNode,
    TableBlock,
    TableCell,
    TableRow,
    TextRun,
)


class TableNormalizationPass:
    """Normalize table structure and fill missing metadata."""

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]:
        result: list[DocumentNode] = []

        for node in nodes:
            if not isinstance(node.content, TableBlock):
                result.append(node)
                continue

            content = node.content
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
            result.append(node.model_copy(update={"content": new_content}))

        return result

    def _normalize_rows(self, rows: list[TableRow]) -> list[TableRow]:
        """Ensure every row has at least one cell and mark header rows."""
        normalized: list[TableRow] = []
        for i, row in enumerate(rows):
            cells = row.cells or [TableCell(content=[TextRun(text="")])]
            is_header = row.is_header or (i == 0 and len(rows) > 1)
            normalized.append(TableRow(cells=cells, is_header=is_header, metadata=row.metadata))
        return normalized

    @staticmethod
    def _extract_headers(rows: list[TableRow]) -> list[str]:
        """Extract header texts from the first row if available."""
        if not rows:
            return []
        first_row = rows[0]
        return ["".join(run.text for run in cell.content) for cell in first_row.cells]
