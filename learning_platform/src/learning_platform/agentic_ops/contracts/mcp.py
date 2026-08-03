"""Typed MCP report contracts consumed by triage."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ReportScope(BaseModel):
    """Scope descriptor for DB report queries."""

    kind: Literal["global", "course", "document"]
    course_id: int | None = None
    document_id: str | None = None

    @model_validator(mode="after")
    def _validate_scope_fields(self) -> ReportScope:
        if self.kind == "course" and self.course_id is None:
            raise ValueError("course_id is required when scope kind is 'course'")
        if self.kind == "document" and not self.document_id:
            raise ValueError("document_id is required when scope kind is 'document'")
        if self.kind == "global":
            return self
        return self


class MissingEntryTable(BaseModel):
    """Missing-table hint returned directly by report service."""

    table_name: str
    severity: Literal["info", "warning", "error"]
    reason: str
    expected_rule: str
    observed_row_count: int
    related_tables: list[str] = Field(default_factory=list)


class ColumnNullStat(BaseModel):
    """Per-column null/empty/invalid counts for requiredness checks."""

    column_name: str
    null_count: int
    empty_string_count: int
    invalid_count: int
    required: bool


class ForeignKeyGap(BaseModel):
    """Orphaned child references for a table relation."""

    relation_name: str
    child_table: str
    parent_table: str
    orphan_count: int
    sample_orphans: list[dict[str, Any]] = Field(default_factory=list)


class TableEntryRow(BaseModel):
    """Optional row payload for deep diagnostics."""

    row_data: dict[str, Any]


class TableReport(BaseModel):
    """Report page data for a single table."""

    table_name: str
    row_count: int
    required_column_stats: list[ColumnNullStat] = Field(default_factory=list)
    foreign_key_gaps: list[ForeignKeyGap] = Field(default_factory=list)
    rows: list[TableEntryRow] = Field(default_factory=list)
    is_expected_non_empty: bool = False


class DatabaseEntriesReportPage(BaseModel):
    """Paginated report payload emitted by MCP report tools."""

    report_id: str
    generated_at: datetime
    scope: ReportScope
    tables: list[TableReport] = Field(default_factory=list)
    missing_entry_tables: list[MissingEntryTable] = Field(default_factory=list)
    next_cursor: str | None = None


class PrepareDeleteDocumentProcessRunsRequest(BaseModel):
    """Prepare request for deleting specific LP document-process rows."""

    process_ids: list[int] = Field(default_factory=list)
    reason: str
    requested_by: str

    @model_validator(mode="after")
    def _validate_payload(self) -> PrepareDeleteDocumentProcessRunsRequest:
        if not self.process_ids:
            raise ValueError("process_ids must contain at least one id")
        if any(process_id <= 0 for process_id in self.process_ids):
            raise ValueError("process_ids must contain positive integers")
        if not self.reason.strip():
            raise ValueError("reason is required")
        if not self.requested_by.strip():
            raise ValueError("requested_by is required")
        return self


class ExecuteDeleteDocumentProcessRunsRequest(BaseModel):
    """Execute request for an already prepared destructive action."""

    action_id: str
    requested_by: str

    @model_validator(mode="after")
    def _validate_payload(self) -> ExecuteDeleteDocumentProcessRunsRequest:
        if not self.action_id.strip():
            raise ValueError("action_id is required")
        if not self.requested_by.strip():
            raise ValueError("requested_by is required")
        return self


class RollBackAgentActionRequest(BaseModel):
    """Rollback request for a previously executed action."""

    action_id: str
    requested_by: str
    reason: str

    @model_validator(mode="after")
    def _validate_payload(self) -> RollBackAgentActionRequest:
        if not self.action_id.strip():
            raise ValueError("action_id is required")
        if not self.requested_by.strip():
            raise ValueError("requested_by is required")
        if not self.reason.strip():
            raise ValueError("reason is required")
        return self


class PreparedAgentActionResult(BaseModel):
    """Result payload from prepare phase for destructive actions."""

    action_id: str
    action_type: str
    status: Literal["prepared", "already_prepared"]
    precheck_passed: bool
    requested_ids: list[int] = Field(default_factory=list)
    target_process_ids: list[int] = Field(default_factory=list)
    missing_process_ids: list[int] = Field(default_factory=list)
    affected_row_count: int
    affected_file_count: int
    integrity_hash: str
    expires_at: datetime | None = None


class ExecutedAgentActionResult(BaseModel):
    """Result payload from execute phase for destructive actions."""

    action_id: str
    action_type: str
    status: Literal["applied", "already_applied"]
    deleted_process_ids: list[int] = Field(default_factory=list)
    missing_process_ids: list[int] = Field(default_factory=list)
    deleted_pipeline_log_count: int
    affected_row_count: int
    affected_file_count: int
    applied_at: datetime | None = None


class CancelAgentActionRequest(BaseModel):
    """Cancel request for a previously prepared action."""

    action_id: str
    requested_by: str
    reason: str

    @model_validator(mode="after")
    def _validate_payload(self) -> CancelAgentActionRequest:
        if not self.action_id.strip():
            raise ValueError("action_id is required")
        if not self.requested_by.strip():
            raise ValueError("requested_by is required")
        if not self.reason.strip():
            raise ValueError("reason is required")
        return self


class CanceledAgentActionResult(BaseModel):
    """Result payload from cancel phase for destructive actions."""

    action_id: str
    action_type: str
    status: Literal["canceled", "already_canceled"]
    canceled_at: datetime | None = None


class RolledBackAgentActionResult(BaseModel):
    """Result payload from rollback phase for destructive actions."""

    action_id: str
    action_type: str
    status: Literal["rolled_back", "already_rolled_back"]
    restored_row_count: int
    rolled_back_at: datetime | None = None


class SliceDocumentPagesRequest(BaseModel):
    """Request payload for managed-document page slicing."""

    mode: Literal["path", "base64"]
    start_page: int
    end_page: int
    source_path: str | None = None
    source_pdf_base64: str | None = None
    filename: str | None = None

    @model_validator(mode="after")
    def _validate_payload(self) -> SliceDocumentPagesRequest:
        if self.start_page <= 0:
            raise ValueError("start_page must be >= 1")
        if self.end_page < self.start_page:
            raise ValueError("end_page must be greater than or equal to start_page")
        if self.mode == "path":
            if not self.source_path or not self.source_path.strip():
                raise ValueError("source_path is required when mode='path'")
            return self
        if not self.source_pdf_base64 or not self.source_pdf_base64.strip():
            raise ValueError("source_pdf_base64 is required when mode='base64'")
        return self


class SliceDocumentPagesResult(BaseModel):
    """Result payload for managed-document page slicing."""

    doc_id: str
    mode: Literal["path", "base64"]
    orig_filename: str
    orig_path: str
    sliced_filename: str
    sliced_path: str | None = None
    start_page: int
    end_page: int
    total_pages: int
    sliced_page_count: int
    sliced_size_bytes: int
    sliced_sha256: str
    sliced_pdf_base64: str | None = None


class ManagedDocumentEntry(BaseModel):
    """Managed document inventory item from MCP storage."""

    doc_id: str
    filename: str
    path: str
    size_bytes: int
    sha256: str
    page_count: int
    created_at: datetime
    source_mode: Literal["path", "base64"]
    source_path: str | None = None
