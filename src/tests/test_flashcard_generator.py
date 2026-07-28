"""Unit tests for the LP FlashcardSeed generator.

Tests the stateless extraction logic in:
  learning_platform/stages/flashcard_generator/generator.py

Uses simple stub objects instead of the full pipeline to stay fast and
dependency-free.
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import uuid4


# Add LP src to path
_lp_src = str(Path(__file__).resolve().parents[3] / "learning_platform" / "src")
if _lp_src not in sys.path:
    sys.path.insert(0, _lp_src)

from learning_platform.stages.flashcard_generator.generator import (  # noqa: E402
    FlashcardSeed,
    _seeds_from_pipeline_result,
)


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_node(block_type: str, **kwargs: Any) -> SimpleNamespace:
    content = SimpleNamespace(type=block_type, **kwargs)
    return SimpleNamespace(id=uuid4(), content=content)


def _make_result(nodes: list) -> SimpleNamespace:
    document = SimpleNamespace(nodes=nodes)
    return SimpleNamespace(document=document)


# ── Tests ─────────────────────────────────────────────────────────────────


class TestSeedsFromPipelineResult:
    def test_definition_node_produces_seed(self):
        node = _make_node("definition", term="Gradient", definition="Rate of change")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert len(seeds) == 1
        assert seeds[0].front == "Gradient"
        assert seeds[0].back == "Rate of change"
        assert seeds[0].source_type == "definition"

    def test_equation_node_with_label_produces_seed(self):
        node = _make_node(
            "equation", latex=r"E = mc^2", label="Energy-mass equivalence"
        )
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert len(seeds) == 1
        assert seeds[0].front == "Energy-mass equivalence"
        assert seeds[0].back == r"E = mc^2"
        assert seeds[0].source_type == "equation"

    def test_equation_node_without_label_uses_fallback(self):
        node = _make_node("equation", latex=r"\alpha + \beta", label="")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds[0].front == "Equation"

    def test_definition_missing_term_skipped(self):
        node = _make_node("definition", term="", definition="Some definition")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_definition_missing_definition_skipped(self):
        node = _make_node("definition", term="Term", definition="")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_equation_missing_latex_skipped(self):
        node = _make_node("equation", latex="", label="Label")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_unrelated_node_types_ignored(self):
        nodes = [
            _make_node("paragraph", text="Some text"),
            _make_node("heading", text="Chapter 1"),
            _make_node("figure", caption="A chart"),
        ]
        result = _make_result(nodes)
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_mixed_nodes_extracts_only_definition_and_equation(self):
        nodes = [
            _make_node("paragraph", text="intro"),
            _make_node("definition", term="Loss", definition="Error measure"),
            _make_node("heading", text="Section 2"),
            _make_node("equation", latex=r"\nabla L", label="Gradient"),
        ]
        result = _make_result(nodes)
        seeds = _seeds_from_pipeline_result(result)
        assert len(seeds) == 2
        types = {s.source_type for s in seeds}
        assert types == {"definition", "equation"}

    def test_source_node_id_set_correctly(self):
        node = _make_node("definition", term="Bias", definition="Offset term")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds[0].source_node_id == str(node.id)

    def test_no_document_returns_empty(self):
        result = SimpleNamespace(document=None)
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_no_nodes_returns_empty(self):
        result = _make_result([])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []

    def test_exception_in_node_returns_empty_gracefully(self):
        # Node with no content attribute should not crash
        bad_node = SimpleNamespace(id=uuid4())  # no 'content' attribute
        result = SimpleNamespace(document=SimpleNamespace(nodes=[bad_node]))
        # Should not raise
        seeds = _seeds_from_pipeline_result(result)
        assert isinstance(seeds, list)

    def test_multiple_definitions_all_extracted(self):
        nodes = [
            _make_node("definition", term=f"Term{i}", definition=f"Def{i}")
            for i in range(5)
        ]
        result = _make_result(nodes)
        seeds = _seeds_from_pipeline_result(result)
        assert len(seeds) == 5

    def test_whitespace_only_term_skipped(self):
        node = _make_node("definition", term="   ", definition="Something")
        result = _make_result([node])
        seeds = _seeds_from_pipeline_result(result)
        assert seeds == []


class TestFlashcardSeedDataclass:
    def test_fields(self):
        seed = FlashcardSeed(front="F", back="B", source_type="definition")
        assert seed.front == "F"
        assert seed.back == "B"
        assert seed.source_type == "definition"
        assert seed.source_node_id is None

    def test_with_source_node_id(self):
        seed = FlashcardSeed(
            front="F", back="B", source_type="equation", source_node_id="abc-123"
        )
        assert seed.source_node_id == "abc-123"
