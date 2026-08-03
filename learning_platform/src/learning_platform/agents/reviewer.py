"""Reviewer agent - LLM-based structured review generation."""

from __future__ import annotations

import base64
import json
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, TypedDict
from uuid import UUID

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnableLambda
from langgraph.graph import END, START, StateGraph

from learning_platform.agents.reviewer_models import (
    DocumentSlice,
    PageReview,
    ReviewerDocumentReviewRequest,
    ReviewerDocumentReviewResponse,
    ReviewPageRangeRequest,
)
from learning_platform.capabilities.reviewer_render import ReviewerRenderService
from learning_platform.capabilities.reviewer_render.pymupdf_verifier import PyMuPdfVerifier
from learning_platform.infrastructure.persistence.repositories.reviewer_run import (
    ReviewerPageResultRepository,
    ReviewerRunRepository,
)
from learning_platform.models.book import BookPage

_LOG = logging.getLogger(__name__)

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


SYSTEM_PROMPT = """You are a careful educational content reviewer.

Review the provided content and return a strict JSON object with this shape:
{
  "summary": "string",
  "strengths": ["string"],
  "issues": [
    {
      "title": "string",
      "severity": "low|medium|high",
      "details": "string"
    }
  ],
  "recommendations": ["string"],
  "verdict": "approved|needs_revision|rejected",
  "confidence": 0.0
}

Rules:
- Output valid JSON only.
- Do not include markdown code fences.
- Do not invent facts not supported by the provided content.
- Keep recommendations actionable and specific.
"""


USER_PROMPT_TEMPLATE = """Review the following content:

CONTENT:
---------------
{content}
---------------
"""


def _build_messages(inputs: dict[str, Any]) -> list[SystemMessage | HumanMessage]:
    content = str(inputs["content"])
    return [
        SystemMessage(content=SYSTEM_PROMPT),
        HumanMessage(content=USER_PROMPT_TEMPLATE.format(content=content)),
    ]


def _extract_json(text: str) -> dict[str, Any]:
    cleaned = text.strip()

    if "```" in cleaned:
        start = cleaned.find("```")
        next_newline = cleaned.find("\n", start)
        if next_newline != -1:
            end = cleaned.rfind("```")
            if end > next_newline:
                cleaned = cleaned[next_newline + 1 : end].strip()

    first_brace = cleaned.find("{")
    last_brace = cleaned.rfind("}")
    if first_brace != -1 and last_brace > first_brace:
        cleaned = cleaned[first_brace : last_brace + 1]

    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        return {"raw": text, "error": "Failed to parse JSON from LLM output"}

    if isinstance(parsed, dict):
        return parsed
    return {"raw": parsed}


class _ReviewerWorkflowState(TypedDict, total=False):
    request: ReviewerDocumentReviewRequest
    resolved_doc: _LpDocumentRecord
    canonical_pages: dict[int, BookPage]
    page_numbers: list[int]
    page_index: int
    slices: list[DocumentSlice]
    page_reviews: list[PageReview]
    run_id: UUID
    response_payload: dict[str, Any]
    workflow_error: str
    workflow_error_type: str


@dataclass(frozen=True)
class _SinglePageReviewResult:
    page_review: PageReview
    page_slice: DocumentSlice | None
    canonical_pdf_bytes: bytes | None


class ReviewerAgent:
    """LLM-based reviewer that returns structured JSON feedback."""

    def __init__(
        self,
        llm: BaseChatModel | None = None,
        mcp_action_client: Any | None = None,
        document_lookup: Callable[[ReviewerDocumentReviewRequest], Awaitable[Any]] | None = None,
        book_pages_lookup: Callable[[UUID], Awaitable[dict[int, BookPage]]] | None = None,
        render_service: Any | None = None,
        verifier: Any | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
        reviewer_run_repository_factory: Callable[[Any], ReviewerRunRepository] | None = None,
        reviewer_page_result_repository_factory: Callable[[Any], ReviewerPageResultRepository]
        | None = None,
        max_pages_per_request: int = 20,
    ) -> None:
        self._llm = llm
        self._chain: Any = None
        self._mcp_action_client = mcp_action_client
        self._document_lookup = document_lookup or self._default_document_lookup
        self._book_pages_lookup = book_pages_lookup or self._default_book_pages_lookup
        self._render_service = render_service or self._build_default_render_service()
        self._verifier = verifier or PyMuPdfVerifier()
        self._session_factory = session_factory
        self._reviewer_run_repository_factory = (
            reviewer_run_repository_factory or ReviewerRunRepository
        )
        self._reviewer_page_result_repository_factory = (
            reviewer_page_result_repository_factory or ReviewerPageResultRepository
        )
        self._max_pages_per_request = max(1, int(max_pages_per_request))

    @staticmethod
    def _build_default_render_service() -> ReviewerRenderService:
        from learning_platform.agentic_ops.settings import AgenticOpsSettings

        settings = AgenticOpsSettings()
        generated_root = Path(settings.mcp_managed_docs) / "reviewer_generated"
        return ReviewerRenderService(reviewer_generated_root=generated_root)

    @property
    def llm(self) -> BaseChatModel:
        if self._llm is None:
            from learning_platform.agents.llm import LLMFactory
            from learning_platform.config import get_settings

            self._llm = LLMFactory.create(get_settings())
        return self._llm

    def _build_chain(self) -> Any:
        if self._chain is None:
            prompt = RunnableLambda(_build_messages)
            parser = RunnableLambda(_extract_json)
            self._chain = prompt | self.llm | StrOutputParser() | parser
        return self._chain

    @property
    def mcp_action_client(self) -> Any:
        if self._mcp_action_client is None:
            from learning_platform.agentic_ops import AgenticOpsSettings
            from learning_platform.agentic_ops.mcp.client import McpActionClient

            settings = AgenticOpsSettings()
            self._mcp_action_client = McpActionClient(
                endpoint=settings.action_mcp_endpoint,
                timeout_seconds=settings.mcp_timeout_seconds,
                api_key=settings.action_mcp_api_key,
            )
        return self._mcp_action_client

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        if self._session_factory is None:
            from learning_platform.api.deps import get_session_factory

            self._session_factory = get_session_factory()
        return self._session_factory

    def review(self, content: str) -> dict[str, Any]:
        chain = self._build_chain()
        return chain.invoke({"content": content})

    async def areview(self, content: str) -> dict[str, Any]:
        chain = self._build_chain()
        return await chain.ainvoke({"content": content})

    async def areview_document(
        self,
        request: ReviewerDocumentReviewRequest,
    ) -> dict[str, Any]:
        _LOG.debug(
            "Starting reviewer document workflow: requested_lp_documents_id=%s page_ranges=%s",
            request.lp_documents_id,
            [f"{row.start_page}-{row.end_page}" for row in request.page_ranges],
        )
        async with self.session_factory() as session:
            run_repo = self._reviewer_run_repository_factory(session)
            page_repo = self._reviewer_page_result_repository_factory(session)
            graph = self._build_document_review_graph(run_repo=run_repo, page_repo=page_repo)
            final_state = await graph.ainvoke(
                {
                    "request": request,
                    "page_index": 0,
                    "slices": [],
                    "page_reviews": [],
                }
            )
            await session.commit()

        workflow_error = final_state.get("workflow_error")
        if workflow_error:
            _LOG.debug(
                "Reviewer document workflow failed: requested_lp_documents_id=%s error=%s",
                request.lp_documents_id,
                workflow_error,
            )
            if final_state.get("workflow_error_type") == "ValueError":
                raise ValueError(workflow_error)
            raise RuntimeError(workflow_error)

        response_payload = final_state.get("response_payload")
        if not isinstance(response_payload, dict):
            raise RuntimeError("Reviewer workflow did not produce a valid response payload")
        _LOG.debug(
            "Reviewer document workflow completed: requested_lp_documents_id=%s "
            "aggregate_verdict=%s reviewed_pages=%s",
            request.lp_documents_id,
            response_payload.get("aggregate_verdict"),
            len(response_payload.get("page_reviews", [])),
        )
        return response_payload

    def _build_document_review_graph(
        self,
        *,
        run_repo: ReviewerRunRepository,
        page_repo: ReviewerPageResultRepository,
    ) -> Any:
        graph = StateGraph(_ReviewerWorkflowState)

        async def prepare_context(
            state: _ReviewerWorkflowState,
        ) -> _ReviewerWorkflowState:
            try:
                request = state.get("request")
                if request is None:
                    raise RuntimeError("Reviewer workflow request state is missing")
                resolved_doc_raw = await self._document_lookup(request)
                resolved_doc = _LpDocumentRecord(
                    lp_documents_id=UUID(str(getattr(resolved_doc_raw, "lp_documents_id", ""))),
                    resolved_document_name=str(
                        getattr(resolved_doc_raw, "resolved_document_name", "")
                    ),
                    source_path=str(getattr(resolved_doc_raw, "source_path", "")),
                )
                if not resolved_doc.resolved_document_name or not resolved_doc.source_path:
                    raise ValueError("Document lookup returned invalid record")

                canonical_pages = await self._book_pages_lookup(resolved_doc.lp_documents_id)
                page_numbers = self._expand_page_ranges(request.page_ranges)
                if len(page_numbers) > self._max_pages_per_request:
                    raise ValueError(
                        "requested page count exceeds "
                        f"max_pages_per_request={self._max_pages_per_request}"
                    )

                _LOG.debug(
                    "Reviewer prepare_context: requested_lp_documents_id=%s "
                    "resolved_lp_documents_id=%s pages=%s canonical_pages=%s",
                    request.lp_documents_id,
                    resolved_doc.lp_documents_id,
                    page_numbers,
                    sorted(canonical_pages.keys()),
                )

                return {
                    "resolved_doc": resolved_doc,
                    "canonical_pages": canonical_pages,
                    "page_numbers": page_numbers,
                }
            except Exception as exc:
                _LOG.debug("Reviewer prepare_context error: %s", exc)
                return {
                    "workflow_error": str(exc),
                    "workflow_error_type": type(exc).__name__,
                }

        async def create_run(state: _ReviewerWorkflowState) -> _ReviewerWorkflowState:
            if state.get("workflow_error"):
                return {}

            request = state.get("request")
            resolved_doc = state.get("resolved_doc")
            page_numbers = state.get("page_numbers")
            if request is None or resolved_doc is None or page_numbers is None:
                return {
                    "workflow_error": (
                        "Reviewer workflow context is incomplete before run creation"
                    ),
                    "workflow_error_type": "RuntimeError",
                }

            try:
                run_row = await run_repo.create_processing_run(
                    requested_lp_documents_id=request.lp_documents_id,
                    resolved_lp_documents_id=resolved_doc.lp_documents_id,
                    resolved_document_name=resolved_doc.resolved_document_name,
                    metadata={
                        "reviewed_page_numbers": page_numbers,
                        "reviewed_pages_count": len(page_numbers),
                        "max_pages_per_request": self._max_pages_per_request,
                    },
                )
                _LOG.debug(
                    "Reviewer create_run: run_id=%s requested_lp_documents_id=%s",
                    run_row.id,
                    request.lp_documents_id,
                )
                return {"run_id": run_row.id}
            except Exception as exc:
                _LOG.debug("Reviewer create_run error: %s", exc)
                return {
                    "workflow_error": str(exc),
                    "workflow_error_type": type(exc).__name__,
                }

        async def review_page(state: _ReviewerWorkflowState) -> _ReviewerWorkflowState:
            if state.get("workflow_error"):
                return {}

            page_numbers = state.get("page_numbers")
            page_index = state.get("page_index")
            if page_numbers is None or page_index is None:
                return {
                    "workflow_error": "Reviewer workflow page state is missing",
                    "workflow_error_type": "RuntimeError",
                }
            if page_index >= len(page_numbers):
                return {}

            resolved_doc = state.get("resolved_doc")
            canonical_pages = state.get("canonical_pages")
            page_reviews = state.get("page_reviews")
            slices = state.get("slices")
            if (
                resolved_doc is None
                or canonical_pages is None
                or page_reviews is None
                or slices is None
            ):
                return {
                    "workflow_error": "Reviewer workflow context is incomplete before page review",
                    "workflow_error_type": "RuntimeError",
                }
            page_number = page_numbers[page_index]

            try:
                page_result = await self._review_single_page(
                    resolved_doc=resolved_doc,
                    canonical_page=canonical_pages.get(page_number),
                    page_number=page_number,
                )

                page_review = page_result.page_review
                page_slice = page_result.page_slice

                next_reviews = [*page_reviews, page_review]
                next_slices = [*slices]
                extracted_text_char_count = 0
                if page_slice is not None:
                    next_slices.append(page_slice)
                    extracted_text_char_count = page_slice.extracted_text_char_count

                run_id = state.get("run_id")
                if run_id is None:
                    raise RuntimeError(
                        "Reviewer run identifier missing while persisting page result"
                    )

                page_row = await page_repo.create_page_result(
                    reviewer_run_id=run_id,
                    lp_documents_id=resolved_doc.lp_documents_id,
                    page_number=page_number,
                    review_status=page_review.review_status,
                    review_error=page_review.review_error,
                    extracted_text_char_count=extracted_text_char_count,
                    summary=page_review.summary,
                    strengths=list(page_review.strengths),
                    issues=[issue.model_dump(mode="json") for issue in page_review.issues],
                    recommendations=list(page_review.recommendations),
                    verdict=page_review.verdict,
                    confidence=page_review.confidence,
                    metadata=dict(page_review.metadata),
                )

                if page_result.canonical_pdf_bytes is not None:
                    next_metadata = dict(page_review.metadata)
                    page_id = f"{page_number}_{page_row.id}"
                    try:
                        generated_pdf_path = self._render_service.persist_generated_pdf(
                            pdf_bytes=page_result.canonical_pdf_bytes,
                            document_name=resolved_doc.resolved_document_name,
                            page_id=page_id,
                        )
                        next_metadata["generated_canonical_pdf_path"] = generated_pdf_path
                        _LOG.debug(
                            "Persisted generated canonical PDF: run_id=%s page_number=%s "
                            "page_result_id=%s path=%s",
                            run_id,
                            page_number,
                            page_row.id,
                            generated_pdf_path,
                        )
                    except Exception as exc:
                        next_metadata["generated_canonical_pdf_persist_error"] = str(exc)
                        _LOG.debug(
                            "Failed persisting generated canonical PDF: run_id=%s page_number=%s "
                            "page_result_id=%s error=%s",
                            run_id,
                            page_number,
                            page_row.id,
                            exc,
                        )

                    page_review.metadata = next_metadata
                    page_row.metadata_json = next_metadata

                _LOG.debug(
                    "Reviewer review_page result: run_id=%s page_number=%s status=%s verdict=%s",
                    run_id,
                    page_number,
                    page_review.review_status,
                    page_review.verdict,
                )

                return {
                    "page_reviews": next_reviews,
                    "slices": next_slices,
                    "page_index": page_index + 1,
                }
            except Exception as exc:
                _LOG.debug("Reviewer review_page error: page_number=%s error=%s", page_number, exc)
                return {
                    "workflow_error": str(exc),
                    "workflow_error_type": type(exc).__name__,
                }

        async def finalize_run(state: _ReviewerWorkflowState) -> _ReviewerWorkflowState:
            if state.get("workflow_error"):
                return {}

            request = state.get("request")
            resolved_doc = state.get("resolved_doc")
            page_reviews = state.get("page_reviews")
            page_numbers = state.get("page_numbers")
            slices = state.get("slices")
            if (
                request is None
                or resolved_doc is None
                or page_reviews is None
                or page_numbers is None
                or slices is None
            ):
                return {
                    "workflow_error": (
                        "Reviewer workflow context is incomplete during finalization"
                    ),
                    "workflow_error_type": "RuntimeError",
                }

            aggregate_verdict = self._aggregate_verdict(page_reviews)
            aggregate_summary = self._build_aggregate_summary(page_reviews)
            metadata: dict[str, object] = {
                "reviewed_page_numbers": page_numbers,
                "reviewed_pages_count": len(page_numbers),
                "max_pages_per_request": self._max_pages_per_request,
            }

            response = ReviewerDocumentReviewResponse(
                requested_lp_documents_id=request.lp_documents_id,
                resolved_lp_documents_id=resolved_doc.lp_documents_id,
                resolved_document_name=resolved_doc.resolved_document_name,
                slices=slices,
                page_reviews=page_reviews,
                aggregate_verdict=aggregate_verdict,
                aggregate_summary=aggregate_summary,
                metadata=metadata,
            )

            try:
                run_id = state.get("run_id")
                if run_id is None:
                    raise RuntimeError("Reviewer run identifier missing during completion")

                run_row = await run_repo.find_by_id(run_id)
                if run_row is None:
                    raise RuntimeError("Reviewer run record not found during completion")

                await run_repo.mark_completed(
                    run_row,
                    aggregate_verdict=aggregate_verdict,
                    aggregate_summary=aggregate_summary,
                    metadata=metadata,
                )
                _LOG.debug(
                    "Reviewer finalize_run: run_id=%s aggregate_verdict=%s",
                    run_id,
                    aggregate_verdict,
                )
                return {"response_payload": response.model_dump(mode="json")}
            except Exception as exc:
                _LOG.debug("Reviewer finalize_run error: %s", exc)
                return {
                    "workflow_error": str(exc),
                    "workflow_error_type": type(exc).__name__,
                }

        async def fail_run(state: _ReviewerWorkflowState) -> _ReviewerWorkflowState:
            run_id = state.get("run_id")
            if run_id is None:
                return {}

            run_row = await run_repo.find_by_id(run_id)
            if run_row is None:
                return {}

            page_numbers = state.get("page_numbers", [])
            processed_count = len(state.get("page_reviews", []))
            await run_repo.mark_failed(
                run_row,
                error_message=state.get("workflow_error", "Reviewer workflow failed"),
                metadata={
                    "reviewed_page_numbers": page_numbers,
                    "reviewed_pages_count": len(page_numbers),
                    "processed_pages_count": processed_count,
                    "max_pages_per_request": self._max_pages_per_request,
                },
            )
            _LOG.debug(
                "Reviewer fail_run: run_id=%s error=%s",
                run_id,
                state.get("workflow_error", "Reviewer workflow failed"),
            )
            return {}

        def route_prepare(state: _ReviewerWorkflowState) -> str:
            if state.get("workflow_error"):
                return "end"
            return "create_run"

        def route_create_run(state: _ReviewerWorkflowState) -> str:
            if state.get("workflow_error"):
                return "fail_run"
            return "review_page"

        def route_review_page(state: _ReviewerWorkflowState) -> str:
            if state.get("workflow_error"):
                return "fail_run"
            page_index = state.get("page_index")
            page_numbers = state.get("page_numbers")
            if (
                page_index is not None
                and page_numbers is not None
                and page_index < len(page_numbers)
            ):
                return "review_page"
            return "finalize_run"

        def route_finalize(state: _ReviewerWorkflowState) -> str:
            if state.get("workflow_error"):
                return "fail_run"
            return "end"

        graph.add_node("prepare_context", prepare_context)
        graph.add_node("create_run", create_run)
        graph.add_node("review_page", review_page)
        graph.add_node("finalize_run", finalize_run)
        graph.add_node("fail_run", fail_run)

        graph.add_edge(START, "prepare_context")
        graph.add_conditional_edges(
            "prepare_context",
            route_prepare,
            {
                "create_run": "create_run",
                "end": END,
            },
        )
        graph.add_conditional_edges(
            "create_run",
            route_create_run,
            {
                "review_page": "review_page",
                "fail_run": "fail_run",
            },
        )
        graph.add_conditional_edges(
            "review_page",
            route_review_page,
            {
                "review_page": "review_page",
                "finalize_run": "finalize_run",
                "fail_run": "fail_run",
            },
        )
        graph.add_conditional_edges(
            "finalize_run",
            route_finalize,
            {
                "fail_run": "fail_run",
                "end": END,
            },
        )
        graph.add_edge("fail_run", END)
        return graph.compile()

    async def _review_single_page(
        self,
        *,
        resolved_doc: _LpDocumentRecord,
        canonical_page: BookPage | None,
        page_number: int,
    ) -> _SinglePageReviewResult:
        if canonical_page is None:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="canonical_missing",
                    review_error="Canonical BookPage not found for requested page",
                ),
                page_slice=None,
                canonical_pdf_bytes=None,
            )

        try:
            canonical_artifacts = self._render_service.render_book_page(canonical_page)
        except Exception as exc:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="canonical_render_error",
                    review_error=str(exc),
                ),
                page_slice=None,
                canonical_pdf_bytes=None,
            )

        try:
            slice_result = await self.mcp_action_client.slice_document_pages(
                mode="path",
                start_page=page_number,
                end_page=page_number,
                source_path=resolved_doc.source_path,
                filename=resolved_doc.resolved_document_name,
            )
            extracted_text = self._extract_text_from_slice_result(slice_result)
            actual_pdf_bytes = self._pdf_bytes_from_slice_result(slice_result)
            actual_png_bytes = self._render_service.pdf_bytes_to_png_bytes(actual_pdf_bytes)
        except Exception as exc:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="source_page_error",
                    review_error=str(exc),
                ),
                page_slice=None,
                canonical_pdf_bytes=canonical_artifacts.pdf_bytes,
            )

        try:
            verification = self._verifier.compare_page_pdfs(
                actual_pdf_bytes=actual_pdf_bytes,
                generated_pdf_bytes=canonical_artifacts.pdf_bytes,
            )
        except Exception as exc:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="deterministic_verifier_error",
                    review_error=str(exc),
                    verdict="needs_revision",
                    confidence=1.0,
                ),
                page_slice=DocumentSlice(
                    lp_documents_id=resolved_doc.lp_documents_id,
                    page_number=page_number,
                    extracted_text_char_count=len(extracted_text),
                ),
                canonical_pdf_bytes=canonical_artifacts.pdf_bytes,
            )
        if verification.should_skip_llm:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="deterministic_mismatch",
                    review_error=(
                        "Deterministic verifier found mismatch: "
                        f"text_similarity_ratio={verification.text_similarity_ratio}, "
                        f"missing_token_count={verification.missing_token_count}, "
                        f"image_count_actual={verification.image_count_actual}, "
                        f"image_count_generated={verification.image_count_generated}, "
                        f"font_count_actual={verification.font_count_actual}, "
                        f"font_count_generated={verification.font_count_generated}"
                    ),
                    verdict="needs_revision",
                    confidence=1.0,
                    issues=[
                        {
                            "title": "Deterministic page mismatch",
                            "severity": "high",
                            "details": (
                                "Generated canonical page diverges from actual page in text "
                                "and/or assets before LLM review."
                            ),
                        }
                    ],
                    recommendations=[
                        "Investigate canonical page rendering fidelity and missing content.",
                        "Verify book assembly and item serialization for this page.",
                    ],
                ),
                page_slice=DocumentSlice(
                    lp_documents_id=resolved_doc.lp_documents_id,
                    page_number=page_number,
                    extracted_text_char_count=len(extracted_text),
                ),
                canonical_pdf_bytes=canonical_artifacts.pdf_bytes,
            )

        try:
            review_payload = await self._review_page_pair(
                page_number=page_number,
                actual_png_bytes=actual_png_bytes,
                generated_png_bytes=canonical_artifacts.png_bytes,
                actual_text=extracted_text,
                generated_text=canonical_artifacts.text_summary,
            )
            page_review = PageReview.model_validate(
                {
                    "page_number": page_number,
                    "review_status": "reviewed",
                    "summary": review_payload.get("summary", ""),
                    "strengths": review_payload.get("strengths", []),
                    "issues": review_payload.get("issues", []),
                    "recommendations": review_payload.get("recommendations", []),
                    "verdict": review_payload.get("verdict", "needs_revision"),
                    "confidence": review_payload.get("confidence", 0.0),
                }
            )
            if page_review.confidence is None:
                page_review = page_review.model_copy(update={"confidence": 0.0})

            page_review.metadata = {
                **getattr(page_review, "metadata", {}),
                "deterministic_verifier": verification.to_dict(),
            }
        except Exception as exc:
            return _SinglePageReviewResult(
                page_review=PageReview(
                    page_number=page_number,
                    review_status="llm_review_error",
                    review_error=str(exc),
                ),
                page_slice=DocumentSlice(
                    lp_documents_id=resolved_doc.lp_documents_id,
                    page_number=page_number,
                    extracted_text_char_count=len(extracted_text),
                ),
                canonical_pdf_bytes=canonical_artifacts.pdf_bytes,
            )

        return _SinglePageReviewResult(
            page_review=page_review,
            page_slice=DocumentSlice(
                lp_documents_id=resolved_doc.lp_documents_id,
                page_number=page_number,
                extracted_text_char_count=len(extracted_text),
            ),
            canonical_pdf_bytes=canonical_artifacts.pdf_bytes,
        )

    async def _review_page_pair(
        self,
        *,
        page_number: int,
        actual_png_bytes: bytes,
        generated_png_bytes: bytes,
        actual_text: str,
        generated_text: str,
    ) -> dict[str, Any]:
        actual_png_b64 = self._render_service.to_base64(actual_png_bytes)
        generated_png_b64 = self._render_service.to_base64(generated_png_bytes)

        human_content: list[dict[str, Any]] = [
            {
                "type": "text",
                "text": (
                    f"Review page {page_number}. Compare ACTUAL page vs GENERATED canonical page. "
                    "Assess alignment, missing/extra content, "
                    "fidelity, and instructional quality. "
                    "Use both images and text snippets."
                    "\n\nACTUAL PAGE EXTRACTED TEXT:\n"
                    f"{actual_text}\n\n"
                    "GENERATED CANONICAL PAGE TEXT:\n"
                    f"{generated_text}"
                ),
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{actual_png_b64}"},
            },
            {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{generated_png_b64}"},
            },
        ]

        response_text = ""
        try:
            response = await self.llm.ainvoke(
                [
                    SystemMessage(content=SYSTEM_PROMPT),
                    HumanMessage(content=human_content),
                ]
            )
            response_text = str(getattr(response, "content", "")).strip()
        except Exception:
            fallback_input = (
                f"Review page {page_number}. Compare ACTUAL vs GENERATED canonical content.\n\n"
                "ACTUAL PAGE EXTRACTED TEXT:\n"
                f"{actual_text}\n\n"
                "GENERATED CANONICAL PAGE TEXT:\n"
                f"{generated_text}\n\n"
                "Note: image payload was unavailable for this model path."
            )
            response = await self.areview(fallback_input)
            return response

        return _extract_json(response_text)

    def _extract_text_from_slice_result(self, slice_result: Any) -> str:
        source_bytes: bytes
        if slice_result.mode == "base64":
            payload = slice_result.sliced_pdf_base64
            if not isinstance(payload, str) or not payload.strip():
                raise ValueError("slice result for base64 mode is missing sliced_pdf_base64")
            source_bytes = base64.b64decode(payload)
            return self._extract_pdf_text(source_bytes=source_bytes, path=None)

        if not isinstance(slice_result.sliced_path, str) or not slice_result.sliced_path.strip():
            raise ValueError("slice result for path mode is missing sliced_path")
        return self._extract_pdf_text(source_bytes=None, path=slice_result.sliced_path)

    def _pdf_bytes_from_slice_result(self, slice_result: Any) -> bytes:
        if slice_result.mode == "base64":
            payload = slice_result.sliced_pdf_base64
            if not isinstance(payload, str) or not payload.strip():
                raise ValueError("slice result for base64 mode is missing sliced_pdf_base64")
            return base64.b64decode(payload)

        if not isinstance(slice_result.sliced_path, str) or not slice_result.sliced_path.strip():
            raise ValueError("slice result for path mode is missing sliced_path")
        return self._render_service.load_pdf_bytes_from_path(slice_result.sliced_path)

    @staticmethod
    def _extract_pdf_text(*, source_bytes: bytes | None, path: str | None) -> str:
        try:
            import pymupdf
        except Exception as exc:
            raise RuntimeError(
                "PyMuPDF dependency is required for document text extraction"
            ) from exc

        if source_bytes is not None:
            doc = pymupdf.open(stream=source_bytes, filetype="pdf")
        elif path is not None:
            doc = pymupdf.open(path)
        else:
            raise ValueError("Either source_bytes or path must be provided")

        try:
            page_text: list[str] = []
            for page in doc:
                page_text.append(page.get_text())
            extracted = "\n".join(page_text).strip()
        finally:
            doc.close()

        if not extracted:
            return "[No extractable text from sliced PDF]"
        return extracted

    @staticmethod
    def _expand_page_ranges(ranges: list[ReviewPageRangeRequest]) -> list[int]:
        seen: set[int] = set()
        ordered_pages: list[int] = []
        for page_range in ranges:
            for page_number in range(page_range.start_page, page_range.end_page + 1):
                if page_number in seen:
                    continue
                seen.add(page_number)
                ordered_pages.append(page_number)
        return ordered_pages

    @staticmethod
    def _aggregate_verdict(page_reviews: list[PageReview]) -> str:
        successful_reviews = [
            review for review in page_reviews if review.review_status == "reviewed"
        ]
        if not successful_reviews:
            return "needs_revision"

        verdicts = {
            review.verdict
            for review in successful_reviews
            if review.verdict in {"approved", "needs_revision", "rejected"}
        }
        if "rejected" in verdicts:
            return "rejected"
        if "needs_revision" in verdicts:
            return "needs_revision"
        return "approved"

    @staticmethod
    def _build_aggregate_summary(page_reviews: list[PageReview]) -> str:
        reviewed_count = sum(1 for review in page_reviews if review.review_status == "reviewed")
        approved_count = sum(1 for review in page_reviews if review.verdict == "approved")
        needs_revision_count = sum(
            1 for review in page_reviews if review.verdict == "needs_revision"
        )
        rejected_count = sum(1 for review in page_reviews if review.verdict == "rejected")
        skipped_count = len(page_reviews) - reviewed_count
        return (
            f"Reviewed {len(page_reviews)} page(s): "
            f"{reviewed_count} reviewed, {skipped_count} skipped/errors; "
            f"{approved_count} approved, "
            f"{needs_revision_count} needs_revision, "
            f"{rejected_count} rejected."
        )

    async def _default_document_lookup(
        self,
        request: ReviewerDocumentReviewRequest,
    ) -> _LpDocumentRecord:
        from learning_platform.api.deps import get_session_factory
        from learning_platform.infrastructure.persistence.repositories.document import (
            DocumentRepository,
        )

        session_factory = get_session_factory()
        async with session_factory() as session:
            document_repo = DocumentRepository(session)
            document = await document_repo.find_document(request.lp_documents_id)

        if document is None:
            raise ValueError(f"Document not found for lp_documents_id={request.lp_documents_id}")

        source_path = document.source.strip()
        if not source_path:
            raise ValueError(
                f"Document source path is empty for lp_documents_id={request.lp_documents_id}"
            )

        resolved_document_name = Path(source_path).name or document.title.strip()
        if not resolved_document_name:
            resolved_document_name = str(request.lp_documents_id)

        return _LpDocumentRecord(
            lp_documents_id=request.lp_documents_id,
            resolved_document_name=resolved_document_name,
            source_path=source_path,
        )

    async def _default_book_pages_lookup(self, lp_documents_id: UUID) -> dict[int, BookPage]:
        from learning_platform.api.deps import get_session_factory
        from learning_platform.infrastructure.persistence.repositories.book import BookRepository

        session_factory = get_session_factory()
        async with session_factory() as session:
            book_repo = BookRepository(session)
            book = await book_repo.find_by_document(lp_documents_id)

        if book is None:
            return {}

        pages: dict[int, BookPage] = {}
        for chapter in book.chapters:
            for lesson in chapter.lessons:
                for page in lesson.pages:
                    pages[int(page.page_number)] = page
        return pages


@dataclass(frozen=True)
class _LpDocumentRecord:
    lp_documents_id: UUID
    resolved_document_name: str
    source_path: str


__all__ = ["ReviewerAgent", "_extract_json"]
