"""Plugin framework base types — category, manifest, and base Protocol.

Every plugin in the learning platform implements the ``Plugin`` Protocol
and provides a ``PluginManifest`` declaring its name, version, category,
and description.  The ``PluginCategory`` enum enumerates the eight
supported plugin categories.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable


class PluginCategory(StrEnum):
    """Categories of plugins the platform supports.

    Each category maps to a stage Protocol defined in
    ``pipeline.base``.  A plugin's manifest declares which
    category it belongs to — the registry uses this to route
    requests to the correct implementation.
    """

    PARSER = "parser"
    ENRICHER = "enricher"
    CONCEPT_EXTRACTOR = "concept_extractor"
    LESSON_GENERATOR = "lesson_generator"
    QUIZ_GENERATOR = "quiz_generator"
    SUMMARIZER = "summarizer"
    SEARCH = "search"
    VECTOR_INDEX = "vector_index"


@dataclass(frozen=True)
class PluginManifest:
    """Metadata describing a plugin.

    Attributes
    ----------
    name :
        Unique identifier (e.g. ``"docling-parser"``).
    version :
        Semver string (e.g. ``"1.0.0"``).
    category :
        Which pipeline capability this plugin provides.
    description :
        Human-readable summary.
    author :
        Plugin author name.
    entry_point :
        Dotted path to the plugin class (for diagnostics only;
        discovery resolves this via entry points).
    """

    name: str
    version: str
    category: PluginCategory
    description: str
    author: str = ""
    entry_point: str = ""


@runtime_checkable
class Plugin(Protocol):
    """Base Protocol every plugin must satisfy.

    A plugin is any object with a read-only ``manifest`` property
    returning a ``PluginManifest``.  Concrete plugins also implement
    the stage-specific Protocol for their category (e.g.
    ``AbstractParser`` for ``PluginCategory.PARSER``).
    """

    @property
    def manifest(self) -> PluginManifest: ...


# ──────────────────────────────────────────────────────────────────────────────
# Category → Protocol mapping
# ──────────────────────────────────────────────────────────────────────────────

# Lazy import to avoid circular dependencies.  Accessed via
# ``get_category_protocol()``.
_CATEGORY_PROTOCOL_MAP: dict[PluginCategory, str] = {
    PluginCategory.PARSER: "learning_platform.pipeline.base.AbstractParser",
    PluginCategory.ENRICHER: "learning_platform.pipeline.base.SemanticEnricher",
    PluginCategory.CONCEPT_EXTRACTOR: "learning_platform.pipeline.base.ConceptExtractor",
    PluginCategory.LESSON_GENERATOR: "learning_platform.pipeline.base.LearningSequenceBuilder",
    PluginCategory.QUIZ_GENERATOR: "learning_platform.pipeline.base.QuizGenerator",
    PluginCategory.SUMMARIZER: "learning_platform.pipeline.base.DocumentSummarizer",
    PluginCategory.SEARCH: "learning_platform.pipeline.base.SearchIndex",
    PluginCategory.VECTOR_INDEX: "learning_platform.pipeline.base.VectorIndexer",
}


def get_category_protocol(category: PluginCategory) -> type:
    """Return the Protocol class associated with *category*.

    Uses lazy imports to avoid circular dependency issues.

    Raises
    ------
    ImportError
        If the Protocol module cannot be imported.
    """
    from importlib import import_module

    dotted = _CATEGORY_PROTOCOL_MAP[category]
    module_path, class_name = dotted.rsplit(".", 1)
    module = import_module(module_path)
    return getattr(module, class_name)
