"""Plugin discovery — automatic loading via Python entry points.

Third-party packages register plugins under the
``learning_platform.plugins`` entry-point group.  The ``PluginLoader``
discovers and instantiates them at runtime.

Entry-point convention (in the third-party ``pyproject.toml``)::

    [project.entry-points."learning_platform.plugins"]
    my_parser = "my_package.plugins:MyParserPlugin"

The entry point must resolve to a **class** (not an instance).  The
loader instantiates each class with no arguments.
"""

from __future__ import annotations

import logging
from importlib.metadata import entry_points
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from learning_platform.plugins.base import Plugin, PluginCategory

_LOG = logging.getLogger(__name__)

_ENTRY_POINT_GROUP = "learning_platform.plugins"


class PluginLoader:
    """Discovers and instantiates plugins from Python entry points.

    Usage::

        loader = PluginLoader()
        all_plugins = loader.discover()
        parsers = loader.discover_by_category(PluginCategory.PARSER)
    """

    def discover(self) -> list[type[Plugin]]:
        """Return all discovered plugin classes (uninstantiated).

        Classes that fail to import are logged and skipped.
        """
        eps = entry_points(group=_ENTRY_POINT_GROUP)
        classes: list[type[Plugin]] = []
        for ep in eps:
            try:
                cls = ep.load()
            except Exception:
                _LOG.exception("Failed to load plugin entry point: %s", ep.name)
                continue
            if isinstance(cls, type):
                classes.append(cls)
            else:
                _LOG.warning(
                    "Entry point %s resolved to %r, not a class — skipping",
                    ep.name,
                    cls,
                )
        return classes

    def discover_by_category(self, category: PluginCategory) -> list[type[Plugin]]:
        """Return plugin classes whose manifest declares *category*.

        Instantiates each class to inspect its manifest, then discards
        the instance.  Errors during instantiation are logged and skipped.
        """
        classes: list[type[Plugin]] = []
        for cls in self.discover():
            try:
                instance = cls()
            except Exception:
                _LOG.exception(
                    "Failed to instantiate plugin class %s",
                    cls.__qualname__,
                )
                continue
            if hasattr(instance, "manifest") and instance.manifest.category == category:
                classes.append(cls)
        return classes

    def load_all(self) -> list[Plugin]:
        """Discover and instantiate all plugins."""
        plugins: list[Plugin] = []
        for cls in self.discover():
            try:
                plugins.append(cls())
            except Exception:
                _LOG.exception("Failed to instantiate plugin class %s", cls.__qualname__)
        return plugins

    def load_by_category(self, category: PluginCategory) -> list[Plugin]:
        """Discover and instantiate plugins matching *category*."""
        plugins: list[Plugin] = []
        for cls in self.discover_by_category(category):
            try:
                plugins.append(cls())
            except Exception:
                _LOG.exception("Failed to instantiate plugin class %s", cls.__qualname__)
        return plugins
