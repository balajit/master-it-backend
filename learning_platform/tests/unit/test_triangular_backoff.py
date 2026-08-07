"""Tests for TriangularBackoff."""

from __future__ import annotations

import pytest

from learning_platform.agents.llm.triangular_backoff import TriangularBackoff


class TestTriangularBackoff:
    def test_sequence_ascending_then_descending(self) -> None:
        b = TriangularBackoff(min_seconds=30, max_seconds=180, step_seconds=30)
        expected = [30, 60, 90, 120, 150, 180, 150, 120, 90, 60, 30, 60]
        for i, exp in enumerate(expected):
            assert b.next() == exp, f"step {i}: expected {exp}, got different"

    def test_never_exceeds_max(self) -> None:
        b = TriangularBackoff(min_seconds=30, max_seconds=180, step_seconds=30)
        for _ in range(50):
            assert b.next() <= 180

    def test_never_goes_below_min(self) -> None:
        b = TriangularBackoff(min_seconds=30, max_seconds=180, step_seconds=30)
        for _ in range(50):
            assert b.next() >= 30

    def test_reset_returns_to_min(self) -> None:
        b = TriangularBackoff(min_seconds=30, max_seconds=180, step_seconds=30)
        # Advance into middle of sequence
        for _ in range(6):
            b.next()
        b.reset()
        assert b.next() == 30
        assert b.next() == 60  # ascending again

    def test_current_property_does_not_advance(self) -> None:
        b = TriangularBackoff(min_seconds=30, max_seconds=90, step_seconds=30)
        assert b.current == 30
        b.next()
        assert b.current == 60
        assert b.current == 60  # unchanged

    def test_custom_parameters(self) -> None:
        b = TriangularBackoff(min_seconds=10, max_seconds=40, step_seconds=10)
        expected = [10, 20, 30, 40, 30, 20, 10, 20]
        for i, exp in enumerate(expected):
            assert b.next() == exp, f"step {i}: expected {exp}"

    def test_invalid_min_raises(self) -> None:
        with pytest.raises(ValueError, match="min_seconds must be positive"):
            TriangularBackoff(min_seconds=0)

    def test_invalid_max_raises(self) -> None:
        with pytest.raises(ValueError, match="max_seconds must be greater than min_seconds"):
            TriangularBackoff(min_seconds=60, max_seconds=30)

    def test_invalid_step_raises(self) -> None:
        with pytest.raises(ValueError, match="step_seconds must be positive"):
            TriangularBackoff(step_seconds=0)
