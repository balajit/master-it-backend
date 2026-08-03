"""CLI driver that parses a document with DoclingAdapter and prints its tree."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from learning_platform.models.document import CanonicalDocument, DocumentNode
from learning_platform.stages.parser.docling_adapter import DoclingAdapter


def _normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _truncate(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    if max_chars == 1:
        return value[:1]
    return f"{value[: max_chars - 1]}..."


def _node_preview(node: DocumentNode, *, max_chars: int) -> str:
    content = node.content
    content_type = getattr(content, "type", "")

    text_value = ""
    text_like = getattr(content, "text", None)
    text_like_plain = getattr(text_like, "plain_text", None)
    if text_like_plain is not None:
        text_value = str(text_like_plain)
    elif content_type == "list":
        items = getattr(content, "items", [])
        item_text: list[str] = []
        for item in items:
            item_text_value = getattr(item, "text", None)
            item_plain_text = getattr(item_text_value, "plain_text", None)
            if item_plain_text is not None:
                item_text.append(str(item_plain_text))
        text_value = " | ".join(item_text)
    elif content_type == "table":
        headers = getattr(content, "headers", [])
        text_value = " | ".join(str(header) for header in headers)
    elif content_type == "equation":
        text_value = str(getattr(content, "latex", ""))
    elif content_type == "code_block":
        text_value = str(getattr(content, "code", ""))
    elif content_type == "figure":
        caption = str(getattr(content, "caption_text", ""))
        alt_text = str(getattr(content, "alt_text", ""))
        text_value = f"{caption} {alt_text}".strip()

    normalized = _normalize_whitespace(text_value)
    return _truncate(normalized, max_chars=max_chars)


def _iter_tree_lines(
    node: DocumentNode,
    *,
    depth: int,
    max_preview_chars: int,
    include_bbox: bool,
    include_source: bool,
) -> list[str]:
    indent = "  " * depth
    node_type = getattr(node.content, "type", "unknown")
    parent_id = str(node.parent_id) if node.parent_id is not None else "root"
    line = (
        f"{indent}- type={node_type} id={node.id} page={node.page} "
        f"seq={node.seq} parent={parent_id} children={len(node.children)}"
    )

    preview = _node_preview(node, max_chars=max_preview_chars)
    if preview:
        line = f'{line} text="{preview}"'

    if include_source:
        line = f"{line} source_page={node.source.page} source_ref={node.source.element_ref or '-'}"

    if include_bbox:
        line = (
            f"{line} bbox=({node.bbox.x:.1f},{node.bbox.y:.1f},"
            f"{node.bbox.width:.1f},{node.bbox.height:.1f})"
        )

    lines = [line]
    for child in node.children:
        lines.extend(
            _iter_tree_lines(
                child,
                depth=depth + 1,
                max_preview_chars=max_preview_chars,
                include_bbox=include_bbox,
                include_source=include_source,
            )
        )
    return lines


def _collect_nodes(node: DocumentNode, output: list[DocumentNode]) -> None:
    output.append(node)
    for child in node.children:
        _collect_nodes(child, output)


def _build_node_type_counts(root: DocumentNode) -> dict[str, int]:
    counts: dict[str, int] = {}
    all_nodes: list[DocumentNode] = []
    _collect_nodes(root, all_nodes)
    for node in all_nodes:
        node_type = str(getattr(node.content, "type", "unknown"))
        counts[node_type] = counts.get(node_type, 0) + 1
    return dict(sorted(counts.items(), key=lambda pair: pair[0]))


def render_tree(
    document: CanonicalDocument,
    *,
    max_preview_chars: int,
    include_bbox: bool,
    include_source: bool,
    include_type_counts: bool,
) -> str:
    if not document.nodes:
        return "CanonicalDocument has no nodes"

    root = document.nodes[0]
    nodes: list[DocumentNode] = []
    _collect_nodes(root, nodes)

    lines = [
        f"title={document.title or '-'}",
        f"source={document.source or '-'}",
        f"metadata_page_count={document.metadata.page_count}",
        f"tree_node_count={len(nodes)}",
    ]

    if include_type_counts:
        type_counts = _build_node_type_counts(root)
        counts_segment = ", ".join(f"{name}:{count}" for name, count in type_counts.items())
        lines.append(f"type_counts={counts_segment}")

    lines.append("tree:")
    lines.extend(
        _iter_tree_lines(
            root,
            depth=0,
            max_preview_chars=max_preview_chars,
            include_bbox=include_bbox,
            include_source=include_source,
        )
    )
    return "\n".join(lines)


def _node_to_tree_dict(node: DocumentNode, *, max_preview_chars: int) -> dict[str, Any]:
    return {
        "id": str(node.id),
        "type": getattr(node.content, "type", "unknown"),
        "page": node.page,
        "seq": node.seq,
        "parent_id": str(node.parent_id) if node.parent_id is not None else None,
        "children_count": len(node.children),
        "preview": _node_preview(node, max_chars=max_preview_chars),
        "children": [
            _node_to_tree_dict(child, max_preview_chars=max_preview_chars)
            for child in node.children
        ],
    }


def build_tree_json(document: CanonicalDocument, *, max_preview_chars: int) -> dict[str, Any]:
    if not document.nodes:
        return {
            "title": document.title,
            "source": document.source,
            "metadata_page_count": document.metadata.page_count,
            "tree_node_count": 0,
            "type_counts": {},
            "tree": None,
        }

    root = document.nodes[0]
    all_nodes: list[DocumentNode] = []
    _collect_nodes(root, all_nodes)

    return {
        "title": document.title,
        "source": document.source,
        "metadata_page_count": document.metadata.page_count,
        "tree_node_count": len(all_nodes),
        "type_counts": _build_node_type_counts(root),
        "tree": _node_to_tree_dict(root, max_preview_chars=max_preview_chars),
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Parse a file with DoclingAdapter and print CanonicalDocument tree output.",
    )
    parser.add_argument("source", help="Path to input document (PDF, DOCX, etc.)")
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print tree output as JSON instead of plain text",
    )
    parser.add_argument(
        "--max-preview-chars",
        type=int,
        default=80,
        help="Maximum characters to print for node text preview (default: 80)",
    )
    parser.add_argument(
        "--include-bbox",
        action="store_true",
        help="Include bounding box coordinates for each node",
    )
    parser.add_argument(
        "--include-source",
        action="store_true",
        help="Include source page/element_ref metadata for each node",
    )
    parser.add_argument(
        "--include-type-counts",
        action="store_true",
        help="Include per-node-type counts in text output",
    )
    return parser.parse_args(argv)


def run(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    source = Path(args.source).expanduser().resolve()

    if not source.exists():
        print(f"error: source file does not exist: {source}", file=sys.stderr)
        return 1
    if not source.is_file():
        print(f"error: source path is not a file: {source}", file=sys.stderr)
        return 1

    adapter = DoclingAdapter()
    if not adapter.supports(str(source)):
        print(
            f"error: unsupported file extension '{source.suffix}' for DoclingAdapter",
            file=sys.stderr,
        )
        return 1

    document = adapter.parse(str(source))

    if args.json_output:
        payload = build_tree_json(document, max_preview_chars=max(0, args.max_preview_chars))
        print(json.dumps(payload, indent=2))
        return 0

    rendered = render_tree(
        document,
        max_preview_chars=max(0, args.max_preview_chars),
        include_bbox=bool(args.include_bbox),
        include_source=bool(args.include_source),
        include_type_counts=bool(args.include_type_counts),
    )
    print(rendered)
    return 0


def main() -> None:
    raise SystemExit(run())


if __name__ == "__main__":
    main()
