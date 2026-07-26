"""Pipeline plugin system — extensible hooks for stage-level customisation.

A ``PipelinePlugin`` is a callable that receives a ``PipelineEvent``
and can inspect or react to it.  The ``PluginRegistry`` manages
registration and lifecycle of plugins.

Plugins are invoked synchronously by the ``EventBus`` after each
event is published.  They can be used for logging, metrics,
validation, side-effects, or even to modify the pipeline state.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from learning_platform.pipeline.events import PipelineEvent

_LOG = logging.getLogger(__name__)


@runtime_checkable
class PipelinePlugin(Protocol):
    """Protocol for pipeline plugins.

    A plugin is any object with a callable ``on_event`` method that
    receives a ``PipelineEvent``.  Plugins can be stateful (holding
    counters, timers, etc.) or stateless (pure functions).
    """

    def on_event(self, event: PipelineEvent) -> None:
        """React to a pipeline event."""
        ...


class PluginRegistry:
    """Manages registered plugins and dispatches events to them.

    Plugins are invoked in registration order.  If a plugin raises,
    the error is logged and dispatch continues to the remaining plugins.
    """

    def __init__(self) -> None:
        self._plugins: list[PipelinePlugin] = []

    def register(self, plugin: PipelinePlugin) -> None:
        """Register a plugin to receive events."""
        if plugin not in self._plugins:
            self._plugins.append(plugin)
            _LOG.debug("Plugin registered: %s", type(plugin).__name__)

    def unregister(self, plugin: PipelinePlugin) -> None:
        """Remove a previously registered plugin."""
        try:
            self._plugins.remove(plugin)
            _LOG.debug("Plugin unregistered: %s", type(plugin).__name__)
        except ValueError:
            pass

    def dispatch(self, event: PipelineEvent) -> None:
        """Dispatch *event* to all registered plugins."""
        for plugin in list(self._plugins):
            try:
                plugin.on_event(event)
            except Exception:
                _LOG.exception(
                    "Plugin %s raised on event %s",
                    type(plugin).__name__,
                    event.event_type,
                )

    @property
    def plugins(self) -> list[PipelinePlugin]:
        """Return a copy of the registered plugins list."""
        return list(self._plugins)
