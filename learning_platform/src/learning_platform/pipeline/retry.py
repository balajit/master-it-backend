"""Retry utilities — configurable retry with exponential backoff.

``RetryPolicy`` controls how many times a failing callable is
retried and how long to wait between attempts.  ``with_retry``
wraps any callable and applies the policy, publishing retry events
to an optional ``EventBus``.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, TypeVar
from uuid import UUID, uuid4

from learning_platform.pipeline.events import EventType, PipelineEvent

_LOG = logging.getLogger(__name__)

F = TypeVar("F", bound=Callable[..., Any])


@dataclass(frozen=True)
class RetryPolicy:
    """Configuration for retry behaviour.

    Attributes
    ----------
    max_retries : int
        Maximum number of retry attempts (0 = no retries).
    base_delay : float
        Seconds to wait after the first failure.
    backoff_factor : float
        Multiplier applied to the delay after each successive failure.
    max_delay : float
        Upper bound on the wait time between retries.
    """

    max_retries: int = 3
    base_delay: float = 0.1
    backoff_factor: float = 2.0
    max_delay: float = 30.0


@dataclass(frozen=True)
class RetryResult:
    """Result of a ``with_retry`` invocation.

    Attributes
    ----------
    value : Any
        The return value of the callable (``None`` if it raised).
    attempts : int
        Total number of attempts (including the first).
    total_seconds : float
        Wall-clock time across all attempts.
    error : Exception | None
        The last exception if all attempts failed.
    """

    value: Any
    attempts: int
    total_seconds: float
    error: Exception | None = None


def with_retry(
    fn: F,
    policy: RetryPolicy | None = None,
    stage_name: str = "",
    event_fn: Callable[[PipelineEvent], None] | None = None,
    pipeline_id: UUID | None = None,
) -> Callable[..., RetryResult]:
    """Return a wrapper that retries *fn* according to *policy*.

    Parameters
    ----------
    fn
        The callable to wrap.
    policy
        Retry configuration.  Defaults to ``RetryPolicy()``.
    stage_name
        Human-readable stage name for event payloads.
    event_fn
        Optional callback to publish retry events to (e.g.,
        ``event_bus.publish``).

    Returns
    -------
    Callable[..., RetryResult]
        A wrapper with the same signature as *fn* that returns a
        ``RetryResult``.
    """
    if policy is None:
        policy = RetryPolicy()

    def wrapper(*args: Any, **kwargs: Any) -> RetryResult:
        last_error: Exception | None = None
        total_start = time.monotonic()

        for attempt in range(1, policy.max_retries + 2):  # +2: first try + retries
            try:
                value = fn(*args, **kwargs)
                elapsed = time.monotonic() - total_start
                return RetryResult(
                    value=value,
                    attempts=attempt,
                    total_seconds=elapsed,
                )
            except Exception as exc:
                last_error = exc
                if attempt > policy.max_retries:
                    break

                delay = min(
                    policy.base_delay * (policy.backoff_factor ** (attempt - 1)),
                    policy.max_delay,
                )
                _LOG.warning(
                    "Stage '%s' attempt %d failed: %s — retrying in %.2fs",
                    stage_name,
                    attempt,
                    exc,
                    delay,
                )

                if event_fn is not None:
                    event_fn(
                        PipelineEvent(
                            event_type=EventType.STAGE_RETRYING,
                            stage=stage_name,
                            data={
                                "attempt": attempt,
                                "max_retries": policy.max_retries,
                                "error": str(exc),
                                "delay": delay,
                                "event_id": str(uuid4()),
                            },
                            pipeline_id=pipeline_id or uuid4(),
                        )
                    )

                time.sleep(delay)

        elapsed = time.monotonic() - total_start
        return RetryResult(
            value=None,
            attempts=policy.max_retries + 1,
            total_seconds=elapsed,
            error=last_error,
        )

    return wrapper  # type: ignore[return-value]


def with_retry_async(
    fn: F,
    policy: RetryPolicy | None = None,
    stage_name: str = "",
    event_fn: Callable[[PipelineEvent], None] | None = None,
    pipeline_id: UUID | None = None,
) -> Callable[..., Awaitable[RetryResult]]:
    """Return an async wrapper that retries *fn* according to *policy*.

    The wrapped callable ``fn`` is executed in a worker thread using
    ``asyncio.to_thread`` so event-loop threads are never blocked by
    synchronous stage work. Backoff delays use ``asyncio.sleep``.
    """
    if policy is None:
        policy = RetryPolicy()

    async def wrapper(*args: Any, **kwargs: Any) -> RetryResult:
        last_error: Exception | None = None
        total_start = time.monotonic()

        for attempt in range(1, policy.max_retries + 2):
            try:
                value = await asyncio.to_thread(fn, *args, **kwargs)
                elapsed = time.monotonic() - total_start
                return RetryResult(
                    value=value,
                    attempts=attempt,
                    total_seconds=elapsed,
                )
            except Exception as exc:
                last_error = exc
                if attempt > policy.max_retries:
                    break

                delay = min(
                    policy.base_delay * (policy.backoff_factor ** (attempt - 1)),
                    policy.max_delay,
                )
                _LOG.warning(
                    "Stage '%s' attempt %d failed: %s — retrying in %.2fs",
                    stage_name,
                    attempt,
                    exc,
                    delay,
                )

                if event_fn is not None:
                    event_fn(
                        PipelineEvent(
                            event_type=EventType.STAGE_RETRYING,
                            stage=stage_name,
                            data={
                                "attempt": attempt,
                                "max_retries": policy.max_retries,
                                "error": str(exc),
                                "delay": delay,
                                "event_id": str(uuid4()),
                            },
                            pipeline_id=pipeline_id or uuid4(),
                        )
                    )

                await asyncio.sleep(delay)

        elapsed = time.monotonic() - total_start
        return RetryResult(
            value=None,
            attempts=policy.max_retries + 1,
            total_seconds=elapsed,
            error=last_error,
        )

    return wrapper
