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
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4


# Add LP src to path
_lp_src = str(Path(__file__).resolve().parents[3] / "learning_platform" / "src")
if _lp_src not in sys.path:
    sys.path.insert(0, _lp_src)

# Add app src to path
_src_dir = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from learning_platform.stages.flashcard_generator.generator import (  # noqa: E402
    FlashcardSeed,
    _seeds_from_pipeline_result,
)
from services.flashcard_generator import FlashCardGenerator  # noqa: E402


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


# ── FlashCardGenerator ────────────────────────────────────────────────────────


class _FakeCurator:
    """Sync stand-in for CuratorAgent that records calls and returns a fixed dict."""

    def __init__(self, result: dict[str, Any] | None = None) -> None:
        self.result: dict[str, Any] = result if result is not None else {}
        self.calls: list[str] = []

    def analyze(self, lesson_text: str) -> dict[str, Any]:
        self.calls.append(lesson_text)
        return self.result


class _RaisingCurator:
    def analyze(self, lesson_text: str) -> dict[str, Any]:
        raise RuntimeError("boom")


_DEFAULT_LESSON: object = object()


class TestFlashCardGeneratorGenerate:
    lesson_id = uuid4()

    def _make_generator(self, curator: Any) -> FlashCardGenerator:
        return FlashCardGenerator(lesson_id=self.lesson_id, curator=curator)

    async def _generate(
        self,
        gen: FlashCardGenerator,
        lesson: Any = _DEFAULT_LESSON,
        text: str = "Lesson body text",
    ) -> list[dict[str, str]]:
        found: Any = (
            SimpleNamespace(id=uuid4()) if lesson is _DEFAULT_LESSON else lesson
        )
        gen._get_lesson = AsyncMock(return_value=found)
        gen._extract_lesson_text = AsyncMock(return_value=text)
        return await gen.generate()

    async def test_key_terms_become_front_back_cards(self):
        curator = _FakeCurator(
            result={
                "key_terms": [
                    {"term": "Gradient", "definition": "Rate of change"},
                    {"term": "Loss", "definition": "Error measure"},
                ]
            }
        )
        gen = self._make_generator(curator)
        cards = await self._generate(gen)
        assert cards == [
            {"front": "Gradient", "back": "Rate of change"},
            {"front": "Loss", "back": "Error measure"},
        ]

    async def test_missing_key_terms_returns_empty(self):
        gen = self._make_generator(_FakeCurator(result={"concepts": []}))
        cards = await self._generate(gen)
        assert cards == []

    async def test_non_list_key_terms_returns_empty(self):
        gen = self._make_generator(_FakeCurator(result={"key_terms": "nope"}))
        cards = await self._generate(gen)
        assert cards == []

    async def test_blank_term_or_definition_filtered(self):
        curator = _FakeCurator(
            result={
                "key_terms": [
                    {"term": "  ", "definition": "Blank term"},
                    {"term": "Valid", "definition": "   "},
                    {"term": "Kept", "definition": "Stays"},
                    "not a dict",
                ]
            }
        )
        gen = self._make_generator(curator)
        cards = await self._generate(gen)
        assert cards == [{"front": "Kept", "back": "Stays"}]

    async def test_duplicate_key_terms_deduplicated(self):
        curator = _FakeCurator(
            result={
                "key_terms": [
                    {"term": "Gradient", "definition": "Rate of change"},
                    {"term": "Gradient", "definition": "Rate of change"},
                    {"term": "Loss", "definition": "Error measure"},
                ]
            }
        )
        gen = self._make_generator(curator)
        cards = await self._generate(gen)
        assert len(cards) == 2

    async def test_missing_lesson_returns_empty_without_text_extraction(self):
        gen = self._make_generator(_FakeCurator())
        cards = await self._generate(gen, lesson=None)
        assert cards == []
        gen._extract_lesson_text.assert_not_awaited()

    async def test_blank_lesson_text_returns_empty_without_curator_call(self):
        curator = _FakeCurator(result={"key_terms": [{"term": "T", "definition": "D"}]})
        gen = self._make_generator(curator)
        cards = await self._generate(gen, text="   \n  ")
        assert cards == []
        assert curator.calls == []

    async def test_curator_called_with_concatenated_lesson_text(self):
        curator = _FakeCurator(result={"key_terms": []})
        gen = self._make_generator(curator)
        lesson = SimpleNamespace(id=uuid4())
        await self._generate(gen, lesson=lesson, text="All the lesson text")
        assert curator.calls == ["All the lesson text"]
        gen._extract_lesson_text.assert_awaited_once_with(lesson.id)

    async def test_curator_exception_returns_empty_gracefully(self):
        gen = self._make_generator(_RaisingCurator())
        cards = await self._generate(gen)
        assert cards == []

    async def test_scope_defaults_to_lesson(self):
        gen = self._make_generator(_FakeCurator())
        assert gen._scope == "lesson"
        assert gen.lesson_id == self.lesson_id


class TestFlashCardGeneratorItemText:
    @staticmethod
    def _text(item: Any) -> str:
        return FlashCardGenerator._item_to_text(item)

    def test_text_heading_code_content(self):
        assert self._text(SimpleNamespace(type="text", content="Alpha")) == "Alpha"
        assert self._text(SimpleNamespace(type="heading", content="Title")) == "Title"
        assert self._text(SimpleNamespace(type="code", content="x = 1")) == "x = 1"

    def test_list_and_form_area_items(self):
        assert self._text(SimpleNamespace(type="list", items=["a", "b"])) == "a\nb"
        assert (
            self._text(SimpleNamespace(type="form_area", items=["Q?", "A!"]))
            == "Q?\nA!"
        )

    def test_table_caption_headers_and_rows(self):
        item = SimpleNamespace(
            type="table",
            caption="Results",
            headers=["Name", "Score"],
            rows=[["Ada", "10"], ["Lin", "9"]],
        )
        assert self._text(item) == "Results\nName | Score\nAda | 10\nLin | 9"

    def test_equation_latex(self):
        assert (
            self._text(SimpleNamespace(type="equation", latex=r"E=mc^2")) == r"E=mc^2"
        )

    def test_question_content(self):
        assert (
            self._text(SimpleNamespace(type="question", content="What is X?"))
            == "What is X?"
        )

    def test_image_caption(self):
        assert self._text(SimpleNamespace(type="image", caption="A chart")) == "A chart"
        assert self._text(SimpleNamespace(type="image", caption="")) == ""

    def test_unknown_type_returns_empty(self):
        assert self._text(SimpleNamespace(type="video", url="http://x")) == ""


class TestFlashCardGeneratorPageText:
    def test_page_joins_item_text(self):
        page = SimpleNamespace(
            items=[
                SimpleNamespace(type="heading", content="Chapter"),
                SimpleNamespace(type="text", content="Body"),
            ]
        )
        assert FlashCardGenerator._page_to_text(page) == "Chapter\nBody"

    def test_page_without_items_returns_empty(self):
        page = SimpleNamespace(items=[])
        assert FlashCardGenerator._page_to_text(page) == ""


class TestFlashCardGeneratorExtractText:
    async def test_extracts_and_joins_all_page_text(self):
        pages = [
            SimpleNamespace(items=[SimpleNamespace(type="text", content="Page one")]),
            SimpleNamespace(
                items=[SimpleNamespace(type="heading", content="Page two")]
            ),
        ]
        fake_repo = SimpleNamespace(find_pages_by_lesson=AsyncMock(return_value=pages))
        fake_session = AsyncMock()
        fake_session.__aenter__ = AsyncMock(return_value=fake_session)
        fake_engine = AsyncMock()

        gen = FlashCardGenerator(lesson_id=uuid4(), curator=_FakeCurator())
        with (
            patch(
                "services.flashcard_generator.create_engine",
                return_value=fake_engine,
            ),
            patch(
                "services.flashcard_generator.create_session_factory",
                return_value=MagicMock(return_value=fake_session),
            ),
            patch(
                "services.flashcard_generator.BookRepository",
                return_value=fake_repo,
            ),
        ):
            lesson_id = uuid4()
            text = await gen._extract_lesson_text(lesson_id)

        assert text == "Page one\nPage two"
        fake_repo.find_pages_by_lesson.assert_awaited_once_with(lesson_id)
        fake_engine.dispose.assert_awaited_once()
