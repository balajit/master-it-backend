"""Domain models for triage run outputs."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from learning_platform.agentic_ops.contracts.mcp import MissingEntryTable, ReportScope

TriageVerdict = Literal["pass", "warn", "fail"]


class TriageFinding(BaseModel):
    """Single deterministic finding emitted by rule evaluation."""

    rule_id: str
    severity: Literal["warning", "error"]
    table_name: str
    message: str
    affected_count: int = 0
    sample: dict[str, Any] = Field(default_factory=dict)


class TriageStats(BaseModel):
    """Aggregate metrics for one triage run."""

    table_count: int = 0
    finding_count: int = 0
    warning_count: int = 0
    error_count: int = 0


class TriageResult(BaseModel):
    """Final triage result payload."""

    report_id: str
    scope: ReportScope
    rule_set_name: str
    rule_set_version: str
    generated_at: datetime
    verdict: TriageVerdict
    findings: list[TriageFinding] = Field(default_factory=list)
    missing_entry_tables: list[MissingEntryTable] = Field(default_factory=list)
    stats: TriageStats = Field(default_factory=TriageStats)
