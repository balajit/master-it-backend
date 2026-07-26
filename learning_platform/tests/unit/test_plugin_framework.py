"""Tests for the plugin framework: base types, discovery, and registry."""

from __future__ import annotations

import pytest

from learning_platform.plugins.base import (
    Plugin,
    PluginCategory,
    PluginManifest,
    get_category_protocol,
)
from learning_platform.plugins.discovery import PluginLoader
from learning_platform.plugins.registry import PluginRegistry

# ── Fixtures ─────────────────────────────────────────────────────────────────


class _StubPlugin:
    """Minimal valid plugin for testing."""

    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="stub",
            version="0.1.0",
            category=PluginCategory.PARSER,
            description="A stub parser",
        )


class _AnotherStubPlugin:
    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="stub-enricher",
            version="0.1.0",
            category=PluginCategory.ENRICHER,
            description="A stub enricher",
        )


class _QuizPlugin:
    @property
    def manifest(self) -> PluginManifest:
        return PluginManifest(
            name="stub-quiz",
            version="0.1.0",
            category=PluginCategory.QUIZ_GENERATOR,
            description="A stub quiz generator",
        )


class _BadPlugin:
    """Plugin whose manifest property raises."""

    @property
    def manifest(self) -> PluginManifest:  # type: ignore[misc]
        raise RuntimeError("broken")


@pytest.fixture
def registry() -> PluginRegistry:
    return PluginRegistry()


@pytest.fixture
def populated_registry() -> PluginRegistry:
    reg = PluginRegistry()
    reg.register(_StubPlugin())
    reg.register(_AnotherStubPlugin())
    reg.register(_QuizPlugin())
    return reg


# ── PluginManifest ───────────────────────────────────────────────────────────


class TestPluginManifest:
    def test_frozen(self) -> None:
        m = PluginManifest(
            name="x", version="1.0", category=PluginCategory.PARSER, description="d"
        )
        with pytest.raises(AttributeError):
            m.name = "y"  # type: ignore[misc]

    def test_default_optional_fields(self) -> None:
        m = PluginManifest(
            name="x", version="1.0", category=PluginCategory.SEARCH, description="d"
        )
        assert m.author == ""
        assert m.entry_point == ""


# ── PluginCategory ───────────────────────────────────────────────────────────


class TestPluginCategory:
    def test_all_eight_categories(self) -> None:
        assert len(PluginCategory) == 8

    def test_values_are_strings(self) -> None:
        for cat in PluginCategory:
            assert isinstance(cat.value, str)
            assert cat.value == cat.value.lower()


# ── Plugin Protocol ──────────────────────────────────────────────────────────


class TestPluginProtocol:
    def test_stub_satisfies_protocol(self) -> None:
        assert isinstance(_StubPlugin(), Plugin)

    def test_object_without_manifest_fails(self) -> None:
        assert not isinstance(object(), Plugin)


# ── get_category_protocol ────────────────────────────────────────────────────


class TestGetCategoryProtocol:
    def test_parser_returns_abstract_parser(self) -> None:
        from learning_platform.pipeline.base import AbstractParser

        assert get_category_protocol(PluginCategory.PARSER) is AbstractParser

    def test_enricher_returns_semantic_enricher(self) -> None:
        from learning_platform.pipeline.base import SemanticEnricher

        assert get_category_protocol(PluginCategory.ENRICHER) is SemanticEnricher

    def test_concept_extractor(self) -> None:
        from learning_platform.pipeline.base import ConceptExtractor

        assert get_category_protocol(PluginCategory.CONCEPT_EXTRACTOR) is ConceptExtractor

    def test_lesson_generator(self) -> None:
        from learning_platform.pipeline.base import LearningSequenceBuilder

        assert get_category_protocol(PluginCategory.LESSON_GENERATOR) is LearningSequenceBuilder

    def test_quiz_generator(self) -> None:
        from learning_platform.pipeline.base import QuizGenerator

        assert get_category_protocol(PluginCategory.QUIZ_GENERATOR) is QuizGenerator

    def test_summarizer(self) -> None:
        from learning_platform.pipeline.base import DocumentSummarizer

        assert get_category_protocol(PluginCategory.SUMMARIZER) is DocumentSummarizer

    def test_search(self) -> None:
        from learning_platform.pipeline.base import SearchIndex

        assert get_category_protocol(PluginCategory.SEARCH) is SearchIndex

    def test_vector_index(self) -> None:
        from learning_platform.pipeline.base import VectorIndexer

        assert get_category_protocol(PluginCategory.VECTOR_INDEX) is VectorIndexer

    def test_all_categories_have_protocol(self) -> None:
        for cat in PluginCategory:
            proto = get_category_protocol(cat)
            assert isinstance(proto, type)


# ── PluginLoader ─────────────────────────────────────────────────────────────


class TestPluginLoader:
    def test_discover_returns_list(self) -> None:
        loader = PluginLoader()
        result = loader.discover()
        assert isinstance(result, list)

    def test_discover_by_category_returns_list(self) -> None:
        loader = PluginLoader()
        result = loader.discover_by_category(PluginCategory.PARSER)
        assert isinstance(result, list)

    def test_load_all_returns_list(self) -> None:
        loader = PluginLoader()
        result = loader.load_all()
        assert isinstance(result, list)

    def test_load_by_category_returns_list(self) -> None:
        loader = PluginLoader()
        result = loader.load_by_category(PluginCategory.PARSER)
        assert isinstance(result, list)


# ── PluginRegistry ───────────────────────────────────────────────────────────


class TestPluginRegistry:
    def test_register_and_retrieve(self, registry: PluginRegistry) -> None:
        plugin = _StubPlugin()
        registry.register(plugin)
        assert registry.get_plugin("stub") is plugin

    def test_register_all(self, registry: PluginRegistry) -> None:
        plugins = [_StubPlugin(), _AnotherStubPlugin()]
        registry.register_all(plugins)
        assert len(registry.loaded_plugins()) == 2

    def test_unregister(self, populated_registry: PluginRegistry) -> None:
        assert populated_registry.unregister("stub") is True
        assert populated_registry.get_plugin("stub") is None

    def test_unregister_nonexistent(self, populated_registry: PluginRegistry) -> None:
        assert populated_registry.unregister("nope") is False

    def test_get_by_category(self, populated_registry: PluginRegistry) -> None:
        parsers = populated_registry.get_by_category(PluginCategory.PARSER)
        assert len(parsers) == 1
        assert parsers[0].manifest.name == "stub"

    def test_get_by_category_empty(self, registry: PluginRegistry) -> None:
        assert registry.get_by_category(PluginCategory.VECTOR_INDEX) == []

    def test_get_plugin_returns_none(self, registry: PluginRegistry) -> None:
        assert registry.get_plugin("nonexistent") is None

    def test_counts(self, populated_registry: PluginRegistry) -> None:
        counts = populated_registry.counts
        assert counts["parser"] == 1
        assert counts["enricher"] == 1
        assert counts["quiz_generator"] == 1
        assert counts["search"] == 0

    def test_no_duplicates(self, registry: PluginRegistry) -> None:
        plugin = _StubPlugin()
        registry.register(plugin)
        registry.register(plugin)
        assert len(registry.get_by_category(PluginCategory.PARSER)) == 1

    def test_get_parser_returns_none_when_empty(self, registry: PluginRegistry) -> None:
        assert registry.get_parser("test.pdf") is None


# ── Category → Protocol mapping completeness ─────────────────────────────────


class TestCategoryProtocolMapping:
    def test_all_categories_mapped(self) -> None:
        from learning_platform.plugins.base import _CATEGORY_PROTOCOL_MAP

        for cat in PluginCategory:
            assert cat in _CATEGORY_PROTOCOL_MAP

    def test_all_protocols_importable(self) -> None:
        from learning_platform.plugins.base import _CATEGORY_PROTOCOL_MAP

        for cat, dotted in _CATEGORY_PROTOCOL_MAP.items():
            proto = get_category_protocol(cat)
            assert proto is not None, f"Failed to import {dotted}"
