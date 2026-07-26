"""Event bus — delivers pipeline events to registered listeners.

The ``EventBus`` Protocol defines the contract; ``SimpleEventBus``
is the default in-process implementation backed by a list of
callables.  The bus is thread-safe for the single-process use case.
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Callable

    from learning_platform.pipeline.events import PipelineEvent

_LOG = logging.getLogger(__name__)


@runtime_checkable
class EventBus(Protocol):
    """Protocol for event delivery."""

    def publish(self, event: PipelineEvent) -> None:
        """Deliver *event* to all registered listeners."""
        ...

    def subscribe(self, listener: Callable[[PipelineEvent], None]) -> None:
        """Register a listener to receive future events."""
        ...

    def unsubscribe(self, listener: Callable[[PipelineEvent], None]) -> None:
        """Remove a previously registered listener."""
        ...


class SimpleEventBus:
    """In-process event bus backed by a list of listener callables.

    Listeners are invoked synchronously in registration order.  If a
    listener raises, the error is logged and delivery continues to the
    remaining listeners.
    """

    def __init__(self) -> None:
        self._listeners: list[Callable[[PipelineEvent], None]] = []

    def publish(self, event: PipelineEvent) -> None:
        """Deliver *event* to all registered listeners."""
        if event.timestamp == 0.0:
            event.timestamp = time.time()

        for listener in list(self._listeners):
            try:
                listener(event)
            except Exception:
                _LOG.exception("Listener %s raised on event %s", listener, event.event_type)

    def subscribe(self, listener: Callable[[PipelineEvent], None]) -> None:
        """Register a listener to receive future events."""
        if listener not in self._listeners:
            self._listeners.append(listener)

    def unsubscribe(self, listener: Callable[[PipelineEvent], None]) -> None:
        """Remove a previously registered listener."""
        with contextlib.suppress(ValueError):
            self._listeners.remove(listener)
