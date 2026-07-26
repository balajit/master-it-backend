"""Pipeline events — typed events emitted by stages during execution.

Every pipeline stage emits ``PipelineEvent`` instances at key
lifecycle points: stage start, completion, failure, and retry
attempts.  The ``EventBus`` delivers these events to registered
listeners (plugins, logging handlers, metrics collectors, etc.).
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    """Kinds of pipeline events."""

    PIPELINE_STARTED = "pipeline.started"
    PIPELINE_COMPLETED = "pipeline.completed"
    PIPELINE_FAILED = "pipeline.failed"

    STAGE_STARTED = "stage.started"
    STAGE_COMPLETED = "stage.completed"
    STAGE_FAILED = "stage.failed"
    STAGE_RETRYING = "stage.retrying"

    PLUGIN_LOADED = "plugin.loaded"
    PLUGIN_UNLOADED = "plugin.unloaded"


class PipelineEvent(BaseModel):
    """An immutable event emitted during pipeline execution.

    Attributes
    ----------
    id : UUID
        Unique event identifier.
    event_type : EventType
        What kind of event this is.
    stage : str
        Name of the stage that emitted the event (or ``"pipeline"``).
    timestamp : float
        Unix timestamp when the event was created.
    data : dict[str, Any]
        Arbitrary payload (e.g., duration, error message, attempt number).
    pipeline_id : UUID
        Groups all events from a single pipeline run.
    """

    id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    stage: str
    timestamp: float = 0.0
    data: dict[str, Any] = Field(default_factory=dict)
    pipeline_id: UUID = Field(default_factory=uuid4)
