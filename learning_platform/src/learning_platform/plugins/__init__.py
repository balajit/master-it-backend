"""Plugin framework — discovery, registration, and lifecycle management.

Public API::

    from learning_platform.plugins import (
        Plugin,
        PluginCategory,
        PluginManifest,
        PluginLoader,
        PluginRegistry,
    )

    # Discover all installed plugins
    loader = PluginLoader()
    plugins = loader.load_all()

    # Register them in the registry
    registry = PluginRegistry()
    registry.register_all(plugins)

    # Retrieve by category
    parsers = registry.get_by_category(PluginCategory.PARSER)

    # Or pick the best parser for a file
    best = registry.get_parser("lecture.pdf")
"""

from learning_platform.plugins.base import (
    Plugin,
    PluginCategory,
    PluginManifest,
    get_category_protocol,
)
from learning_platform.plugins.discovery import PluginLoader
from learning_platform.plugins.registry import PluginRegistry

__all__ = [
    "Plugin",
    "PluginCategory",
    "PluginManifest",
    "PluginLoader",
    "PluginRegistry",
    "get_category_protocol",
]
