from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator


class ReviewPageRangeRequest(BaseModel):
    start_page: int = Field(..., ge=1)
    end_page: int = Field(..., ge=1)

    @model_validator(mode="after")
    def validate_range(self) -> ReviewPageRangeRequest:
        if self.end_page < self.start_page:
            raise ValueError("end_page must be greater than or equal to start_page")
        return self


class ReviewerDocumentReviewRequest(BaseModel):
    lp_documents_id: UUID
    page_ranges: list[ReviewPageRangeRequest] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_payload(self) -> ReviewerDocumentReviewRequest:
        if not self.page_ranges:
            raise ValueError("page_ranges must contain at least one range")
        return self


class DocumentSlice(BaseModel):
    lp_documents_id: UUID
    page_number: int = Field(..., ge=1)
    extracted_text_char_count: int = Field(..., ge=0)


class ReviewerIssue(BaseModel):
    title: str
    severity: Literal["low", "medium", "high"]
    details: str


class PageReview(BaseModel):
    page_number: int = Field(..., ge=1)
    review_status: Literal[
        "reviewed",
        "canonical_missing",
        "canonical_render_error",
        "source_page_error",
        "deterministic_mismatch",
        "deterministic_verifier_error",
        "llm_review_error",
    ] = "reviewed"
    review_error: str | None = None
    summary: str = ""
    strengths: list[str] = Field(default_factory=list)
    issues: list[ReviewerIssue] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    verdict: Literal["approved", "needs_revision", "rejected"] | None = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ReviewerDocumentReviewResponse(BaseModel):
    requested_lp_documents_id: UUID
    resolved_lp_documents_id: UUID
    resolved_document_name: str
    slices: list[DocumentSlice] = Field(default_factory=list)
    page_reviews: list[PageReview] = Field(default_factory=list)
    aggregate_verdict: Literal["approved", "needs_revision", "rejected"]
    aggregate_summary: str
    metadata: dict[str, Any] = Field(default_factory=dict)
