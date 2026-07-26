"""Plugin registry — category-aware registration and retrieval.

The ``PluginRegistry`` stores instantiated plugins, indexed by
category.  Consumers look up plugins by category or by specific
stage Protocol.

This is distinct from ``pipeline.plugins.PluginRegistry``, which
manages pipeline *event* hooks.  This registry manages *stage*
plugins — implementations of pipeline stages.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from learning_platform.plugins.base import Plugin, PluginCategory

if TYPE_CHECKING:
    from learning_platform.pipeline.base import AbstractParser

_LOG = logging.getLogger(__name__)


class PluginRegistry:
    """Stores and retrieves stage plugins by category.

    Usage::

        registry = PluginRegistry()
        registry.register(my_parser_plugin)
        parsers = registry.get_by_category(PluginCategory.PARSER)
        best = registry.get_parser("document.pdf")
    """

    def __init__(self) -> None:
        self._plugins: dict[PluginCategory, list[Plugin]] = {cat: [] for cat in PluginCategory}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin under its manifest category."""
        category = plugin.manifest.category
        if plugin not in self._plugins[category]:
            self._plugins[category].append(plugin)
            _LOG.debug(
                "Plugin registered: %s (category=%s)",
                plugin.manifest.name,
                category,
            )

    def register_all(self, plugins: list[Plugin]) -> None:
        """Register multiple plugins."""
        for plugin in plugins:
            self.register(plugin)

    def unregister(self, name: str) -> bool:
        """Remove a plugin by name.  Returns ``True`` if found and removed."""
        for category, plugins in self._plugins.items():
            for i, plugin in enumerate(plugins):
                if plugin.manifest.name == name:
                    plugins.pop(i)
                    _LOG.debug("Plugin unregistered: %s (category=%s)", name, category)
                    return True
        return False

    def get_by_category(self, category: PluginCategory) -> list[Plugin]:
        """Return all registered plugins for *category*."""
        return list(self._plugins[category])

    def get_plugin(self, name: str) -> Plugin | None:
        """Look up a plugin by its manifest name."""
        for plugins in self._plugins.values():
            for plugin in plugins:
                if plugin.manifest.name == name:
                    return plugin
        return None

    def get_parser(self, source: str) -> AbstractParser | None:
        """Pick the best parser plugin for *source*.

        Iterates registered parser plugins, calls ``supports()`` and
        ``confidence()`` on each, and returns the one with the highest
        confidence score.  Returns ``None`` if no parser supports the
        source.
        """
        from learning_platform.pipeline.base import AbstractParser

        best: AbstractParser | None = None
        best_confidence = -1.0

        for plugin in self._plugins[PluginCategory.PARSER]:
            if not isinstance(plugin, AbstractParser):
                continue
            try:
                if not plugin.supports(source):
                    continue
                conf = plugin.confidence(source)
                if conf > best_confidence:
                    best_confidence = conf
                    best = plugin
            except Exception:
                _LOG.exception(
                    "Parser %s raised during supports/confidence for %s",
                    plugin.manifest.name,
                    source,
                )
        return best

    def loaded_plugins(self) -> list[Plugin]:
        """Return a flat list of all registered plugins."""
        return [p for plugins in self._plugins.values() for p in plugins]

    @property
    def counts(self) -> dict[str, int]:
        """Return a summary of plugin counts per category."""
        return {cat.value: len(plugins) for cat, plugins in self._plugins.items()}
