"""NormalizationPass protocol — the contract every structural pass satisfies."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from learning_platform.models.document import DocumentNode


@runtime_checkable
class NormalizationPass(Protocol):
    """A single, composable normalization step.

    A pass receives a flat list of ``DocumentNode`` instances and returns
    a new (possibly modified) list. Passes must not mutate their input.
    """

    def __call__(self, nodes: list[DocumentNode]) -> list[DocumentNode]: ...
