"""MCP contract models for triage reports."""

from __future__ import annotations

from learning_platform.agentic_ops.contracts.mcp import (
    CancelAgentActionRequest,
    CanceledAgentActionResult,
    ColumnNullStat,
    DatabaseEntriesReportPage,
    ExecutedAgentActionResult,
    ExecuteDeleteDocumentProcessRunsRequest,
    ForeignKeyGap,
    ManagedDocumentEntry,
    MissingEntryTable,
    PreparedAgentActionResult,
    PrepareDeleteDocumentProcessRunsRequest,
    ReportScope,
    RollBackAgentActionRequest,
    RolledBackAgentActionResult,
    SliceDocumentPagesRequest,
    SliceDocumentPagesResult,
    TableEntryRow,
    TableReport,
)

__all__ = [
    "ColumnNullStat",
    "CancelAgentActionRequest",
    "CanceledAgentActionResult",
    "DatabaseEntriesReportPage",
    "ExecuteDeleteDocumentProcessRunsRequest",
    "ExecutedAgentActionResult",
    "ForeignKeyGap",
    "MissingEntryTable",
    "ManagedDocumentEntry",
    "PrepareDeleteDocumentProcessRunsRequest",
    "PreparedAgentActionResult",
    "ReportScope",
    "RollBackAgentActionRequest",
    "RolledBackAgentActionResult",
    "SliceDocumentPagesRequest",
    "SliceDocumentPagesResult",
    "TableEntryRow",
    "TableReport",
]
