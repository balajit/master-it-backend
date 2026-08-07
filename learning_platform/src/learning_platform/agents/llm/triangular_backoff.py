"""Triangular backoff schedule for LLM gateway retry.

Generates a repeating triangular wait sequence:

    30 → 60 → 90 → 120 → 150 → 180 → 150 → 120 → 90 → 60 → 30 → 60 → ...

Endpoints (min and max) are not repeated on direction reversal.
``reset()`` restores the position to min_seconds so the next call to
``next()`` returns min_seconds again.
"""

from __future__ import annotations


class TriangularBackoff:
    """Repeating triangular wait schedule.

    Args:
        min_seconds: Floor of the sequence (default 30).
        max_seconds: Ceiling of the sequence (default 180).
        step_seconds: Increment/decrement per step (default 30).
    """

    def __init__(
        self,
        min_seconds: int = 30,
        max_seconds: int = 180,
        step_seconds: int = 30,
    ) -> None:
        if min_seconds <= 0:
            raise ValueError("min_seconds must be positive")
        if max_seconds <= min_seconds:
            raise ValueError("max_seconds must be greater than min_seconds")
        if step_seconds <= 0:
            raise ValueError("step_seconds must be positive")

        self._min = min_seconds
        self._max = max_seconds
        self._step = step_seconds
        self._current = min_seconds
        self._direction: int = 1  # +1 ascending, -1 descending

    @property
    def current(self) -> int:
        """Current wait interval without advancing."""
        return self._current

    def next(self) -> int:
        """Return the current wait interval and advance to the next position."""
        value = self._current

        next_value = self._current + self._direction * self._step

        if next_value >= self._max:
            # Hit or exceeded ceiling — pin to max, flip direction
            self._current = self._max
            self._direction = -1
        elif next_value <= self._min:
            # Hit or passed floor — pin to min, flip direction
            self._current = self._min
            self._direction = 1
        else:
            self._current = next_value

        return value

    def reset(self) -> None:
        """Reset to min_seconds (call when gateway becomes available again)."""
        self._current = self._min
        self._direction = 1
