from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any
from unittest.mock import patch
from uuid import UUID

import pytest
from pydantic import BaseModel

from learning_platform.agents.reviewer import ReviewerAgent, _extract_json
from learning_platform.agents.reviewer_models import (
    ReviewerDocumentReviewRequest,
    ReviewPageRangeRequest,
)
from learning_platform.capabilities.reviewer_render.pymupdf_verifier import (
    PyMuPdfVerificationResult,
)
from learning_platform.capabilities.reviewer_render.service import RenderedPageArtifacts
from learning_platform.models.book import BookPage, TextItem


class _FakeChain:
    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload
        self.invocations: list[dict[str, Any]] = []
        self.ainvocations: list[dict[str, Any]] = []

    def invoke(self, data: dict[str, Any]) -> dict[str, Any]:
        self.invocations.append(data)
        return self._payload

    async def ainvoke(self, data: dict[str, Any]) -> dict[str, Any]:
        self.ainvocations.append(data)
        return self._payload


class _FakeManagedDocEntry(BaseModel):
    doc_id: str
    filename: str
    path: str
    size_bytes: int
    sha256: str
    page_count: int
    created_at: str
    source_mode: str
    source_path: str | None = None


class _FakeSliceResult(BaseModel):
    doc_id: str
    mode: str
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


class _FakeActionClient:
    def __init__(
        self,
        *,
        list_payload: list[_FakeManagedDocEntry],
        slice_payload: _FakeSliceResult,
    ) -> None:
        self._list_payload = list_payload
        self._slice_payload = slice_payload
        self.slice_calls: list[dict[str, Any]] = []
        self.list_calls = 0

    async def list_managed_documents(self) -> list[_FakeManagedDocEntry]:
        self.list_calls += 1
        return self._list_payload

    async def slice_document_pages(self, **kwargs: Any) -> _FakeSliceResult:
        self.slice_calls.append(kwargs)
        return self._slice_payload


@dataclass
class _RunRecord:
    id: UUID
    requested_lp_documents_id: UUID
    resolved_lp_documents_id: UUID
    resolved_document_name: str
    status: str = "processing"
    aggregate_verdict: str | None = None
    aggregate_summary: str = ""
    metadata_json: dict[str, object] | None = None
    error_message: str | None = None
    updated_at: datetime | None = None


@dataclass
class _PageRecord:
    id: int
    reviewer_run_id: UUID
    lp_documents_id: UUID
    page_number: int
    review_status: str
    review_error: str | None
    extracted_text_char_count: int
    summary: str
    strengths_json: list[str]
    issues_json: list[dict[str, object]]
    recommendations_json: list[str]
    verdict: str | None
    confidence: float | None
    metadata_json: dict[str, object]


class _FakeReviewerRunRepository:
    def __init__(self) -> None:
        self.rows: dict[UUID, _RunRecord] = {}

    async def create_processing_run(
        self,
        *,
        requested_lp_documents_id: UUID,
        resolved_lp_documents_id: UUID,
        resolved_document_name: str,
        metadata: dict[str, object] | None = None,
    ) -> _RunRecord:
        row = _RunRecord(
            id=UUID("00000000-0000-0000-0000-00000000aaa1"),
            requested_lp_documents_id=requested_lp_documents_id,
            resolved_lp_documents_id=resolved_lp_documents_id,
            resolved_document_name=resolved_document_name,
            metadata_json=metadata,
        )
        self.rows[row.id] = row
        return row

    async def find_by_id(self, pk: UUID) -> _RunRecord | None:
        return self.rows.get(pk)

    async def mark_completed(
        self,
        row: _RunRecord,
        *,
        aggregate_verdict: str,
        aggregate_summary: str,
        metadata: dict[str, object],
    ) -> None:
        row.status = "completed"
        row.aggregate_verdict = aggregate_verdict
        row.aggregate_summary = aggregate_summary
        row.metadata_json = metadata

    async def mark_failed(
        self,
        row: _RunRecord,
        *,
        error_message: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        row.status = "failed"
        row.error_message = error_message
        if metadata is not None:
            row.metadata_json = metadata


class _FakeReviewerPageResultRepository:
    def __init__(self) -> None:
        self.rows: list[_PageRecord] = []
        self._next_id = 1

    async def create_page_result(
        self,
        *,
        reviewer_run_id: UUID,
        lp_documents_id: UUID,
        page_number: int,
        review_status: str,
        review_error: str | None,
        extracted_text_char_count: int,
        summary: str,
        strengths: list[str],
        issues: list[dict[str, object]],
        recommendations: list[str],
        verdict: str | None,
        confidence: float | None,
        metadata: dict[str, object],
    ) -> _PageRecord:
        row = _PageRecord(
            id=self._next_id,
            reviewer_run_id=reviewer_run_id,
            lp_documents_id=lp_documents_id,
            page_number=page_number,
            review_status=review_status,
            review_error=review_error,
            extracted_text_char_count=extracted_text_char_count,
            summary=summary,
            strengths_json=strengths,
            issues_json=issues,
            recommendations_json=recommendations,
            verdict=verdict,
            confidence=confidence,
            metadata_json=metadata,
        )
        self._next_id += 1
        self.rows.append(row)
        return row


class _FakeSession:
    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
        _ = (exc_type, exc, tb)
        return False

    async def commit(self) -> None:
        return None


class _FakeSessionFactory:
    def __call__(self) -> _FakeSession:
        return _FakeSession()


@dataclass
class _PersistenceFakes:
    session_factory: _FakeSessionFactory
    run_repo: _FakeReviewerRunRepository
    page_repo: _FakeReviewerPageResultRepository


def _build_persistence_fakes() -> _PersistenceFakes:
    session_factory = _FakeSessionFactory()
    run_repo = _FakeReviewerRunRepository()
    page_repo = _FakeReviewerPageResultRepository()
    return _PersistenceFakes(
        session_factory=session_factory,
        run_repo=run_repo,
        page_repo=page_repo,
    )


def _persistence_kwargs(persistence: _PersistenceFakes) -> dict[str, Any]:
    return {
        "session_factory": persistence.session_factory,
        "reviewer_run_repository_factory": lambda _session: persistence.run_repo,
        "reviewer_page_result_repository_factory": lambda _session: persistence.page_repo,
    }


@dataclass(frozen=True)
class _FakeAppDocumentRecord:
    lp_documents_id: UUID
    resolved_document_name: str
    source_path: str


class _FakeRenderService:
    def __init__(self) -> None:
        self.persist_calls: list[dict[str, str]] = []

    def render_book_page(self, book_page: BookPage) -> RenderedPageArtifacts:
        _ = book_page
        return RenderedPageArtifacts(
            pdf_bytes=b"%PDF-generated",
            png_bytes=b"generated-png",
            text_summary="Generated page summary",
            item_count=1,
            truncated=False,
        )

    def pdf_bytes_to_png_bytes(self, pdf_bytes: bytes) -> bytes:
        _ = pdf_bytes
        return b"actual-png"

    def to_base64(self, payload: bytes) -> str:
        return base64.b64encode(payload).decode("ascii")

    def load_pdf_bytes_from_path(self, path: str) -> bytes:
        _ = path
        return b"%PDF-source"

    def persist_generated_pdf(self, *, pdf_bytes: bytes, document_name: str, page_id: str) -> str:
        _ = pdf_bytes
        self.persist_calls.append({"document_name": document_name, "page_id": page_id})
        return f"/tmp/reviewer_generated/{document_name}/{page_id}.pdf"


class _FakeVerifier:
    def compare_page_pdfs(
        self,
        *,
        actual_pdf_bytes: bytes,
        generated_pdf_bytes: bytes,
    ) -> PyMuPdfVerificationResult:
        _ = (actual_pdf_bytes, generated_pdf_bytes)
        return PyMuPdfVerificationResult(
            text_char_count_actual=100,
            text_char_count_generated=100,
            token_count_actual=10,
            token_count_generated=10,
            text_similarity_ratio=1.0,
            missing_token_count=0,
            missing_token_examples=[],
            image_count_actual=0,
            image_count_generated=0,
            font_count_actual=1,
            font_count_generated=1,
            has_text_loss=False,
            has_asset_mismatch=False,
        )


class _MismatchVerifier:
    def compare_page_pdfs(
        self,
        *,
        actual_pdf_bytes: bytes,
        generated_pdf_bytes: bytes,
    ) -> PyMuPdfVerificationResult:
        _ = (actual_pdf_bytes, generated_pdf_bytes)
        return PyMuPdfVerificationResult(
            text_char_count_actual=200,
            text_char_count_generated=120,
            token_count_actual=30,
            token_count_generated=15,
            text_similarity_ratio=0.45,
            missing_token_count=8,
            missing_token_examples=["missing", "tokens"],
            image_count_actual=2,
            image_count_generated=0,
            font_count_actual=3,
            font_count_generated=1,
            has_text_loss=True,
            has_asset_mismatch=True,
        )


def test_extract_json_parses_plain_json() -> None:
    payload = {"verdict": "approved", "confidence": 0.9}
    raw = json.dumps(payload)
    parsed = _extract_json(raw)
    assert parsed == payload


def test_extract_json_parses_markdown_fenced_json() -> None:
    payload = {"verdict": "needs_revision", "confidence": 0.6}
    raw = f"```json\n{json.dumps(payload)}\n```"
    parsed = _extract_json(raw)
    assert parsed == payload


def test_extract_json_returns_error_payload_for_invalid_json() -> None:
    parsed = _extract_json("not valid json")
    assert parsed["error"] == "Failed to parse JSON from LLM output"
    assert "raw" in parsed


def test_reviewer_agent_review_uses_chain_invoke() -> None:
    payload = {
        "summary": "Good structure",
        "strengths": ["Clear objective"],
        "issues": [],
        "recommendations": ["Add one worked example"],
        "verdict": "approved",
        "confidence": 0.92,
    }
    fake_chain = _FakeChain(payload)
    agent = ReviewerAgent(llm=None)
    agent._chain = fake_chain

    result = agent.review("Sample content")

    assert result == payload
    assert fake_chain.invocations == [{"content": "Sample content"}]


@pytest.mark.asyncio
async def test_reviewer_agent_areview_uses_chain_ainvoke() -> None:
    payload = {
        "summary": "Needs improvements",
        "strengths": ["Relevant topic"],
        "issues": [
            {
                "title": "Missing examples",
                "severity": "medium",
                "details": "No concrete examples were included.",
            }
        ],
        "recommendations": ["Add two concrete examples"],
        "verdict": "needs_revision",
        "confidence": 0.74,
    }
    fake_chain = _FakeChain(payload)
    agent = ReviewerAgent(llm=None)
    agent._chain = fake_chain

    result = await agent.areview("Sample content")

    assert result == payload
    assert fake_chain.ainvocations == [{"content": "Sample content"}]


@pytest.mark.asyncio
async def test_reviewer_agent_areview_document_integrates_mcp_tools() -> None:
    review_payload = {
        "summary": "Structured and clear",
        "strengths": ["Good progression"],
        "issues": [],
        "recommendations": ["Add one challenge question"],
        "verdict": "needs_revision",
        "confidence": 0.93,
    }
    fake_chain = _FakeChain(review_payload)
    fake_client = _FakeActionClient(
        list_payload=[
            _FakeManagedDocEntry(
                doc_id="d1",
                filename="orig.pdf",
                path="/tmp/mcp/orig/orig.pdf",
                size_bytes=100,
                sha256="abc",
                page_count=10,
                created_at="2026-01-01T00:00:00Z",
                source_mode="path",
                source_path="/tmp/source.pdf",
            )
        ],
        slice_payload=_FakeSliceResult(
            doc_id="d1",
            mode="path",
            orig_filename="orig.pdf",
            orig_path="/tmp/mcp/orig/orig.pdf",
            sliced_filename="slice.pdf",
            sliced_path="/tmp/mcp/sliced/slice.pdf",
            start_page=7,
            end_page=10,
            total_pages=22,
            sliced_page_count=4,
            sliced_size_bytes=2048,
            sliced_sha256="def",
            sliced_pdf_base64=None,
        ),
    )

    async def _lookup(
        request: ReviewerDocumentReviewRequest,
    ) -> _FakeAppDocumentRecord:
        assert request.lp_documents_id == UUID("00000000-0000-0000-0000-000000000001")
        return _FakeAppDocumentRecord(
            lp_documents_id=UUID("00000000-0000-0000-0000-000000000001"),
            resolved_document_name="source.pdf",
            source_path="/tmp/source.pdf",
        )

    persistence = _build_persistence_fakes()
    render_service = _FakeRenderService()

    agent = ReviewerAgent(
        llm=None,
        mcp_action_client=fake_client,
        document_lookup=_lookup,
        book_pages_lookup=lambda _doc_id: _book_pages(),
        render_service=render_service,
        verifier=_FakeVerifier(),
        **_persistence_kwargs(persistence),
    )
    agent._chain = fake_chain

    async def _book_pages() -> dict[int, BookPage]:
        return {
            7: BookPage(page_number=7, items=[TextItem(content="p7", order=1)]),
            8: BookPage(page_number=8, items=[TextItem(content="p8", order=1)]),
        }

    async def _review_page_pair(**kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return review_payload

    agent._review_page_pair = _review_page_pair

    with patch.object(
        ReviewerAgent,
        "_extract_pdf_text",
        return_value="Extracted text for review",
    ):
        result = await agent.areview_document(
            ReviewerDocumentReviewRequest(
                lp_documents_id="00000000-0000-0000-0000-000000000001",
                page_ranges=[ReviewPageRangeRequest(start_page=7, end_page=8)],
            )
        )

    assert len(fake_client.slice_calls) == 2
    assert fake_client.slice_calls[0]["start_page"] == 7
    assert fake_client.slice_calls[1]["start_page"] == 8
    assert result["requested_lp_documents_id"] == "00000000-0000-0000-0000-000000000001"
    assert result["resolved_lp_documents_id"] == "00000000-0000-0000-0000-000000000001"
    assert result["aggregate_verdict"] == "needs_revision"
    assert len(result["page_reviews"]) == 2
    assert result["page_reviews"][0]["review_status"] == "reviewed"
    assert result["slices"][0]["lp_documents_id"] == "00000000-0000-0000-0000-000000000001"
    assert result["metadata"]["reviewed_page_numbers"] == [7, 8]
    assert len(persistence.page_repo.rows) == 2
    assert persistence.run_repo.rows
    saved_run = next(iter(persistence.run_repo.rows.values()))
    assert saved_run.status == "completed"
    assert saved_run.aggregate_verdict == "needs_revision"
    assert render_service.persist_calls[0]["page_id"] == "7_1"
    assert render_service.persist_calls[1]["page_id"] == "8_2"
    assert (
        result["page_reviews"][0]["metadata"]["generated_canonical_pdf_path"]
        == "/tmp/reviewer_generated/source.pdf/7_1.pdf"
    )


@pytest.mark.asyncio
async def test_reviewer_agent_areview_document_enforces_max_pages() -> None:
    fake_chain = _FakeChain(
        {
            "summary": "ok",
            "strengths": [],
            "issues": [],
            "recommendations": [],
            "verdict": "approved",
            "confidence": 0.9,
        }
    )

    async def _lookup(
        request: ReviewerDocumentReviewRequest,
    ) -> _FakeAppDocumentRecord:
        return _FakeAppDocumentRecord(
            lp_documents_id=request.lp_documents_id,
            resolved_document_name="source.pdf",
            source_path="/tmp/source.pdf",
        )

    slice_payload = _FakeSliceResult(
        doc_id="d2",
        mode="path",
        orig_filename="orig.pdf",
        orig_path="/tmp/mcp/orig/orig.pdf",
        sliced_filename="slice.pdf",
        sliced_path="/tmp/mcp/sliced/slice.pdf",
        start_page=1,
        end_page=1,
        total_pages=10,
        sliced_page_count=1,
        sliced_size_bytes=123,
        sliced_sha256="sha",
        sliced_pdf_base64=None,
    )
    fake_client = _FakeActionClient(list_payload=[], slice_payload=slice_payload)
    persistence = _build_persistence_fakes()
    render_service = _FakeRenderService()
    agent = ReviewerAgent(
        llm=None,
        mcp_action_client=fake_client,
        document_lookup=_lookup,
        book_pages_lookup=lambda _doc_id: _book_pages(),
        render_service=render_service,
        verifier=_FakeVerifier(),
        max_pages_per_request=2,
        **_persistence_kwargs(persistence),
    )
    agent._chain = fake_chain

    async def _book_pages() -> dict[int, BookPage]:
        return {
            1: BookPage(page_number=1, items=[TextItem(content="p1", order=1)]),
        }

    with pytest.raises(ValueError, match="max_pages_per_request=2"):
        await agent.areview_document(
            ReviewerDocumentReviewRequest(
                lp_documents_id="00000000-0000-0000-0000-000000000002",
                page_ranges=[ReviewPageRangeRequest(start_page=1, end_page=3)],
            )
        )
    assert not persistence.run_repo.rows
    assert not persistence.page_repo.rows


def test_reviewer_document_review_request_rejects_invalid_lp_documents_id() -> None:
    with pytest.raises(ValueError):
        _ = ReviewerDocumentReviewRequest(
            lp_documents_id="not-a-uuid",
            page_ranges=[ReviewPageRangeRequest(start_page=1, end_page=1)],
        )


def test_reviewer_agent_expand_page_ranges_deduplicates_preserves_order() -> None:
    expanded = ReviewerAgent._expand_page_ranges(
        [
            ReviewPageRangeRequest(start_page=2, end_page=4),
            ReviewPageRangeRequest(start_page=3, end_page=5),
        ]
    )
    assert expanded == [2, 3, 4, 5]


@pytest.mark.asyncio
async def test_reviewer_agent_areview_document_marks_canonical_missing_without_failing() -> None:
    fake_chain = _FakeChain(
        {
            "summary": "ok",
            "strengths": [],
            "issues": [],
            "recommendations": [],
            "verdict": "approved",
            "confidence": 0.8,
        }
    )
    slice_payload = _FakeSliceResult(
        doc_id="d9",
        mode="path",
        orig_filename="orig.pdf",
        orig_path="/tmp/mcp/orig/orig.pdf",
        sliced_filename="slice.pdf",
        sliced_path="/tmp/mcp/sliced/slice.pdf",
        start_page=2,
        end_page=2,
        total_pages=10,
        sliced_page_count=1,
        sliced_size_bytes=123,
        sliced_sha256="sha",
        sliced_pdf_base64=None,
    )
    fake_client = _FakeActionClient(list_payload=[], slice_payload=slice_payload)

    async def _lookup(
        request: ReviewerDocumentReviewRequest,
    ) -> _FakeAppDocumentRecord:
        return _FakeAppDocumentRecord(
            lp_documents_id=request.lp_documents_id,
            resolved_document_name="source.pdf",
            source_path="/tmp/source.pdf",
        )

    async def _book_pages(_doc_id: UUID) -> dict[int, BookPage]:
        return {2: BookPage(page_number=2, items=[TextItem(content="page 2", order=1)])}

    persistence = _build_persistence_fakes()
    render_service = _FakeRenderService()

    agent = ReviewerAgent(
        llm=None,
        mcp_action_client=fake_client,
        document_lookup=_lookup,
        book_pages_lookup=_book_pages,
        render_service=render_service,
        verifier=_FakeVerifier(),
        **_persistence_kwargs(persistence),
    )
    agent._chain = fake_chain

    async def _review_page_pair(**kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {
            "summary": "ok",
            "strengths": [],
            "issues": [],
            "recommendations": [],
            "verdict": "approved",
            "confidence": 0.8,
        }

    agent._review_page_pair = _review_page_pair

    with patch.object(
        ReviewerAgent,
        "_extract_pdf_text",
        return_value="Extracted text for review",
    ):
        result = await agent.areview_document(
            ReviewerDocumentReviewRequest(
                lp_documents_id="00000000-0000-0000-0000-000000000011",
                page_ranges=[ReviewPageRangeRequest(start_page=1, end_page=2)],
            )
        )

    assert len(result["page_reviews"]) == 2
    assert result["page_reviews"][0]["review_status"] == "canonical_missing"
    assert result["page_reviews"][1]["review_status"] == "reviewed"
    assert result["aggregate_verdict"] == "approved"
    assert len(persistence.page_repo.rows) == 2
    assert persistence.page_repo.rows[0].review_status == "canonical_missing"
    assert persistence.page_repo.rows[0].extracted_text_char_count == 0
    assert "generated_canonical_pdf_path" not in result["page_reviews"][0]["metadata"]
    assert result["page_reviews"][1]["metadata"]["generated_canonical_pdf_path"].endswith(
        "/source.pdf/2_2.pdf"
    )
    saved_run = next(iter(persistence.run_repo.rows.values()))
    assert saved_run.status == "completed"


@pytest.mark.asyncio
async def test_reviewer_agent_deterministic_mismatch_skips_llm() -> None:
    fake_chain = _FakeChain(
        {
            "summary": "unused",
            "strengths": [],
            "issues": [],
            "recommendations": [],
            "verdict": "approved",
            "confidence": 0.8,
        }
    )
    slice_payload = _FakeSliceResult(
        doc_id="d7",
        mode="path",
        orig_filename="orig.pdf",
        orig_path="/tmp/mcp/orig/orig.pdf",
        sliced_filename="slice.pdf",
        sliced_path="/tmp/mcp/sliced/slice.pdf",
        start_page=4,
        end_page=4,
        total_pages=10,
        sliced_page_count=1,
        sliced_size_bytes=123,
        sliced_sha256="sha",
        sliced_pdf_base64=None,
    )
    fake_client = _FakeActionClient(list_payload=[], slice_payload=slice_payload)

    async def _lookup(
        request: ReviewerDocumentReviewRequest,
    ) -> _FakeAppDocumentRecord:
        return _FakeAppDocumentRecord(
            lp_documents_id=request.lp_documents_id,
            resolved_document_name="source.pdf",
            source_path="/tmp/source.pdf",
        )

    async def _book_pages(_doc_id: UUID) -> dict[int, BookPage]:
        return {4: BookPage(page_number=4, items=[TextItem(content="page 4", order=1)])}

    persistence = _build_persistence_fakes()
    render_service = _FakeRenderService()

    agent = ReviewerAgent(
        llm=None,
        mcp_action_client=fake_client,
        document_lookup=_lookup,
        book_pages_lookup=_book_pages,
        render_service=render_service,
        verifier=_MismatchVerifier(),
        **_persistence_kwargs(persistence),
    )
    agent._chain = fake_chain

    with patch.object(
        ReviewerAgent,
        "_extract_pdf_text",
        return_value="Extracted text for review",
    ):
        result = await agent.areview_document(
            ReviewerDocumentReviewRequest(
                lp_documents_id="00000000-0000-0000-0000-000000000021",
                page_ranges=[ReviewPageRangeRequest(start_page=4, end_page=4)],
            )
        )

    assert result["page_reviews"][0]["review_status"] == "deterministic_mismatch"
    assert result["page_reviews"][0]["verdict"] == "needs_revision"
    assert result["aggregate_verdict"] == "needs_revision"
    assert len(persistence.page_repo.rows) == 1
    assert persistence.page_repo.rows[0].review_status == "deterministic_mismatch"
    assert result["page_reviews"][0]["metadata"]["generated_canonical_pdf_path"].endswith(
        "/source.pdf/4_1.pdf"
    )


@pytest.mark.asyncio
async def test_reviewer_agent_marks_run_failed_when_page_repo_write_fails() -> None:
    slice_payload = _FakeSliceResult(
        doc_id="d8",
        mode="path",
        orig_filename="orig.pdf",
        orig_path="/tmp/mcp/orig/orig.pdf",
        sliced_filename="slice.pdf",
        sliced_path="/tmp/mcp/sliced/slice.pdf",
        start_page=6,
        end_page=6,
        total_pages=10,
        sliced_page_count=1,
        sliced_size_bytes=123,
        sliced_sha256="sha",
        sliced_pdf_base64=None,
    )
    fake_client = _FakeActionClient(list_payload=[], slice_payload=slice_payload)

    async def _lookup(
        request: ReviewerDocumentReviewRequest,
    ) -> _FakeAppDocumentRecord:
        return _FakeAppDocumentRecord(
            lp_documents_id=request.lp_documents_id,
            resolved_document_name="source.pdf",
            source_path="/tmp/source.pdf",
        )

    async def _book_pages(_doc_id: UUID) -> dict[int, BookPage]:
        return {6: BookPage(page_number=6, items=[TextItem(content="page 6", order=1)])}

    class _FailingPageRepo(_FakeReviewerPageResultRepository):
        async def create_page_result(
            self,
            *,
            reviewer_run_id: UUID,
            lp_documents_id: UUID,
            page_number: int,
            review_status: str,
            review_error: str | None,
            extracted_text_char_count: int,
            summary: str,
            strengths: list[str],
            issues: list[dict[str, object]],
            recommendations: list[str],
            verdict: str | None,
            confidence: float | None,
            metadata: dict[str, object],
        ) -> _PageRecord:
            _ = (
                reviewer_run_id,
                lp_documents_id,
                page_number,
                review_status,
                review_error,
                extracted_text_char_count,
                summary,
                strengths,
                issues,
                recommendations,
                verdict,
                confidence,
                metadata,
            )
            raise RuntimeError("page persistence failed")

    persistence = _build_persistence_fakes()
    persistence.page_repo = _FailingPageRepo()
    render_service = _FakeRenderService()

    agent = ReviewerAgent(
        llm=None,
        mcp_action_client=fake_client,
        document_lookup=_lookup,
        book_pages_lookup=_book_pages,
        render_service=render_service,
        verifier=_FakeVerifier(),
        **_persistence_kwargs(persistence),
    )

    async def _review_page_pair(**kwargs: Any) -> dict[str, Any]:
        _ = kwargs
        return {
            "summary": "ok",
            "strengths": [],
            "issues": [],
            "recommendations": [],
            "verdict": "approved",
            "confidence": 0.9,
        }

    agent._review_page_pair = _review_page_pair

    with (
        patch.object(
            ReviewerAgent,
            "_extract_pdf_text",
            return_value="Extracted text for review",
        ),
        pytest.raises(RuntimeError, match="page persistence failed"),
    ):
        await agent.areview_document(
            ReviewerDocumentReviewRequest(
                lp_documents_id="00000000-0000-0000-0000-000000000031",
                page_ranges=[ReviewPageRangeRequest(start_page=6, end_page=6)],
            )
        )

    saved_run = next(iter(persistence.run_repo.rows.values()))
    assert saved_run.status == "failed"
    assert saved_run.error_message == "page persistence failed"


def test_extract_text_from_slice_result_base64_mode_uses_payload() -> None:
    pdf_payload = base64.b64encode(b"pdf-bytes").decode("ascii")
    slice_result = _FakeSliceResult(
        doc_id="d2",
        mode="base64",
        orig_filename="orig.pdf",
        orig_path="/tmp/mcp/orig/orig.pdf",
        sliced_filename="slice.pdf",
        sliced_path=None,
        start_page=1,
        end_page=1,
        total_pages=1,
        sliced_page_count=1,
        sliced_size_bytes=9,
        sliced_sha256="zzz",
        sliced_pdf_base64=pdf_payload,
    )
    agent = ReviewerAgent(
        llm=None, mcp_action_client=_FakeActionClient(list_payload=[], slice_payload=slice_result)
    )

    with patch.object(ReviewerAgent, "_extract_pdf_text", return_value="decoded") as mocked:
        text = agent._extract_text_from_slice_result(slice_result)

    assert text == "decoded"
    assert mocked.call_count == 1
