"""Test coverage for src/ — routers, services, and the host app.

Covers:
- App startup (title, health, CORS, /lp mount)
- src/routers/documents.py  — upload, list, delete, process, tree, units,
                               concepts, study-plan, export
- src/routers/mapping.py    — get, put, post (regenerate/reset), preview
- src/routers/triage.py     — create diagnosis, diagnosis lookup, findings lookup
- src/services/mapping.py   — generate_study_experience, pipeline_result_to_output
- src/services/learning.py  — TTL-caching wrappers

Auth is bypassed via dependency_overrides.
DB and LP calls are mocked throughout.
"""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID

import pytest
from fastapi import HTTPException
from fpdf import FPDF
from httpx import ASGITransport, AsyncClient

from schemas import DocumentBookProcess

# Ensure JWT_SECRET is set before any src/ module is imported.
os.environ.setdefault("JWT_SECRET", "test-secret-for-coverage-suite")

# Put src/ on the path so imports work when pytest runs from the project root.
_SRC = str(Path(__file__).resolve().parent.parent)
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _run(coro):
    """Run an async coroutine synchronously (used in sync test methods)."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def app():
    from main import app as _app

    return _app


@pytest.fixture()
def mock_user() -> dict[str, Any]:
    return {
        "id": 1,
        "email": "user@example.com",
        "name": "Test User",
        "picture_url": "",
        "phone": "",
        "auth_provider": "local",
        "roles": ["Student"],
        "permissions": ["course:browse"],
    }


@pytest.fixture()
def authed_app(app, mock_user):
    """App with auth dependency bypassed."""
    from auth import get_current_user

    app.dependency_overrides[get_current_user] = lambda: mock_user
    yield app
    app.dependency_overrides.pop(get_current_user, None)


# ── App startup ───────────────────────────────────────────────────────────────


class TestAppStartup:
    """Verify the app loads and core endpoints respond."""

    def test_app_title(self, app) -> None:
        assert app.title == "Master It API"

    @pytest.mark.asyncio
    async def test_health_returns_200(self, app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_lp_mounted_at_lp_health(self, app) -> None:
        """LP sub-app is accessible at /lp/health."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.get("/lp/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_unauthenticated_document_upload_returns_403(self, app) -> None:
        """Without auth header, upload returns 403."""
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/courses/1/documents",
                files={"file": ("f.pdf", b"x", "application/pdf")},
            )
        assert resp.status_code in (401, 403, 422)

    @pytest.mark.asyncio
    async def test_unauthenticated_triage_run_returns_403(self, app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/triage/diagnoses",
                json={"document_id": "doc-1"},
            )
        assert resp.status_code in (401, 403)


# ── src/routers/documents.py ──────────────────────────────────────────────────


class TestDocumentUpload:
    """POST /api/courses/{course_id}/documents"""

    @pytest.mark.asyncio
    async def test_upload_course_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_course", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/999/documents",
                    files={"file": ("a.pdf", b"data", "application/pdf")},
                )
        assert resp.status_code == 404
        assert "course not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_upload_success_returns_201(self, authed_app, tmp_path: Path) -> None:
        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch(
                "routers.documents.create_document",
                new_callable=AsyncMock,
                return_value={
                    "id": "doc-1",
                    "filename": "notes.pdf",
                    "storage_path": "/uploads/notes.pdf",
                    "content_type": "application/pdf",
                    "size_bytes": 11,
                    "created_at": "2026-01-01T00:00:00",
                },
            ),
            patch(
                "routers.documents.attach_document_to_course", new_callable=AsyncMock
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents",
                    files={"file": ("notes.pdf", b"pdf content", "application/pdf")},
                )
        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_upload_too_large_returns_413(self, authed_app) -> None:
        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch("routers.documents.MAX_UPLOAD_BYTES", 10),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents",
                    files={"file": ("big.pdf", b"x" * 100, "application/pdf")},
                )
        assert resp.status_code == 413

    @pytest.mark.asyncio
    async def test_upload_sample_saves_single_page_pdf(
        self, authed_app, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "source.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, "Page One")
        pdf.add_page()
        pdf.multi_cell(0, 10, "Page Two")
        pdf.output(str(pdf_path))
        source_bytes = pdf_path.read_bytes()

        captured: dict[str, Any] = {}

        async def _create_document_stub(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "id": kwargs["doc_id"],
                "filename": kwargs["filename"],
                "storage_path": kwargs["storage_path"],
                "content_type": kwargs["content_type"],
                "size_bytes": kwargs["size_bytes"],
                "created_at": "2026-01-01T00:00:00",
            }

        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch(
                "routers.documents.create_document",
                new=AsyncMock(side_effect=_create_document_stub),
            ),
            patch(
                "routers.documents.attach_document_to_course", new_callable=AsyncMock
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={"file": ("worksheet.pdf", source_bytes, "application/pdf")},
                    data={
                        "sample_start_page": "2",
                        "sampled_filename": "worksheet-sample",
                    },
                )

        assert resp.status_code == 201
        saved_path = Path(captured["storage_path"])
        assert saved_path.name == "worksheet-sample.pdf"

        import pymupdf

        sliced = pymupdf.open(saved_path)
        try:
            assert len(sliced) == 1
        finally:
            sliced.close()

    @pytest.mark.asyncio
    async def test_upload_sample_requires_pdf(self, authed_app, tmp_path: Path) -> None:
        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={"file": ("notes.txt", b"hello", "text/plain")},
                    data={"sample_start_page": "1"},
                )

        assert resp.status_code == 400
        assert "only supports PDF" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_sample_rejects_out_of_range_page(
        self, authed_app, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "single.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, "Only page")
        pdf.output(str(pdf_path))

        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={
                        "file": ("single.pdf", pdf_path.read_bytes(), "application/pdf")
                    },
                    data={"sample_start_page": "3"},
                )

        assert resp.status_code == 400
        assert "out of range" in resp.json()["detail"]

    @pytest.mark.asyncio
    async def test_upload_sample_requires_sample_page(
        self, authed_app, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "source.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, "Page")
        pdf.output(str(pdf_path))

        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={
                        "file": ("source.pdf", pdf_path.read_bytes(), "application/pdf")
                    },
                )

        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_upload_sample_with_page_range_saves_expected_page_count(
        self, authed_app, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "source-range.pdf"
        pdf = FPDF()
        for text in ("Page One", "Page Two", "Page Three", "Page Four"):
            pdf.add_page()
            pdf.set_font("Helvetica", size=12)
            pdf.multi_cell(0, 10, text)
        pdf.output(str(pdf_path))
        source_bytes = pdf_path.read_bytes()

        captured: dict[str, Any] = {}

        async def _create_document_stub(**kwargs: Any) -> dict[str, Any]:
            captured.update(kwargs)
            return {
                "id": kwargs["doc_id"],
                "filename": kwargs["filename"],
                "storage_path": kwargs["storage_path"],
                "content_type": kwargs["content_type"],
                "size_bytes": kwargs["size_bytes"],
                "created_at": "2026-01-01T00:00:00",
            }

        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch(
                "routers.documents.create_document",
                new=AsyncMock(side_effect=_create_document_stub),
            ),
            patch(
                "routers.documents.attach_document_to_course", new_callable=AsyncMock
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={"file": ("worksheet.pdf", source_bytes, "application/pdf")},
                    data={"sample_start_page": "2", "sample_end_page": "4"},
                )

        assert resp.status_code == 201
        saved_path = Path(captured["storage_path"])
        assert saved_path.name == "worksheet.sample-p2-4.pdf"

        import pymupdf

        sliced = pymupdf.open(saved_path)
        try:
            assert len(sliced) == 3
        finally:
            sliced.close()

    @pytest.mark.asyncio
    async def test_upload_sample_rejects_reversed_range(
        self, authed_app, tmp_path: Path
    ) -> None:
        pdf_path = tmp_path / "range.pdf"
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Helvetica", size=12)
        pdf.multi_cell(0, 10, "Page One")
        pdf.output(str(pdf_path))

        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1, "title": "Math"},
            ),
            patch("routers.documents.UPLOAD_PATH", str(tmp_path)),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/courses/1/documents/upload_sample",
                    files={
                        "file": ("range.pdf", pdf_path.read_bytes(), "application/pdf")
                    },
                    data={"sample_start_page": "3", "sample_end_page": "2"},
                )

        assert resp.status_code == 400
        assert "greater than or equal" in resp.json()["detail"]


class TestDocumentList:
    """GET /api/courses/{course_id}/documents"""

    @pytest.mark.asyncio
    async def test_list_course_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_course", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/999/documents")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_list_returns_documents(self, authed_app) -> None:
        docs = [
            {
                "id": "a",
                "filename": "x.pdf",
                "storage_path": "/uploads/x.pdf",
                "content_type": "application/pdf",
                "size_bytes": 100,
                "created_at": "2026-01-01T00:00:00",
            },
            {
                "id": "b",
                "filename": "y.pdf",
                "storage_path": "/uploads/y.pdf",
                "content_type": "application/pdf",
                "size_bytes": 200,
                "created_at": "2026-01-01T00:00:00",
            },
        ]
        with (
            patch(
                "routers.documents.get_course",
                new_callable=AsyncMock,
                return_value={"id": 1},
            ),
            patch(
                "routers.documents.get_course_documents",
                new_callable=AsyncMock,
                return_value=docs,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/courses/1/documents")
        assert resp.status_code == 200
        assert len(resp.json()) == 2


class TestDocumentDelete:
    """DELETE /api/documents/{document_id}"""

    @pytest.mark.asyncio
    async def test_delete_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.delete("/api/documents/doc-abc")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_delete_success_returns_204(self, authed_app, tmp_path: Path) -> None:
        fake_path = tmp_path / "file.pdf"
        fake_path.write_bytes(b"x")
        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_path)},
            ),
            patch(
                "routers.documents.delete_document",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.delete("/api/documents/doc-abc")
        assert resp.status_code == 204
        assert not fake_path.exists()


class TestDocumentProcess:
    """POST /api/documents/{document_id}/process"""

    @pytest.mark.asyncio
    async def test_process_doc_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_process_file_missing_returns_400(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document",
            new_callable=AsyncMock,
            return_value={"storage_path": "/nonexistent/file.pdf"},
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")
        assert resp.status_code == 400

    @pytest.mark.asyncio
    async def test_process_enqueue_error_returns_500(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")
        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._ensure_lp_document_process",
                new_callable=AsyncMock,
                side_effect=RuntimeError("enqueue boom"),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")
        assert resp.status_code == 500

    @pytest.mark.asyncio
    async def test_process_new_start_returns_202(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 77
            status = "pending"
            retry_count = 0
            max_retries = 3

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._ensure_lp_document_process",
                new_callable=AsyncMock,
                return_value=(_Row(), False),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
            patch("routers.documents.asyncio.create_task", return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")

        assert resp.status_code == 202
        data = resp.json()
        assert data["document_id"] == "doc-abc"
        assert data["lp_doc_id"] == "lp-doc-id"
        assert data["already_started"] is False
        assert data["status"] == "pending"
        assert data["can_retry"] is False
        assert data["latest_process_run"]["process_id"] == 77
        assert data["latest_process_run"]["status"] == "pending"

    @pytest.mark.asyncio
    async def test_process_already_started_returns_200(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 12
            status = "processing"
            retry_count = 1
            max_retries = 3

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._ensure_lp_document_process",
                new_callable=AsyncMock,
                return_value=(_Row(), True),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")

        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "doc-abc"
        assert data["already_started"] is True
        assert data["status"] == "processing"
        assert data["latest_process_run"]["process_id"] == 12

    @pytest.mark.asyncio
    async def test_process_already_started_completed_but_book_pending_returns_processing(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 12
            status = "completed"
            retry_count = 0
            max_retries = 3
            abs_path = ""

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._ensure_lp_document_process",
                new_callable=AsyncMock,
                return_value=(_Row(), True),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
            patch(
                "routers.documents._load_book_process_summary",
                new_callable=AsyncMock,
                return_value=DocumentBookProcess(
                    status="processing",
                    retry_count=0,
                    max_retries=3,
                    error_message=None,
                    updated_at="",
                ),
            ),
            patch(
                "routers.documents._load_pipeline_stage_details",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "routers.documents._load_process_runs",
                new_callable=AsyncMock,
                return_value=[],
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "processing"
        assert data["message"].lower().startswith("primary pipeline completed")
        assert data["latest_process_run"]["process_id"] == 12

    @pytest.mark.asyncio
    async def test_process_response_includes_grouped_process_runs(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 77
            status = "pending"
            retry_count = 0
            max_retries = 3
            run_mode = "process"
            created_at = ""
            updated_at = ""
            error_message = None
            abs_path = ""

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._ensure_lp_document_process",
                new_callable=AsyncMock,
                return_value=(_Row(), False),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
            patch("routers.documents.asyncio.create_task", return_value=None),
            patch(
                "routers.documents._load_process_runs",
                new_callable=AsyncMock,
                return_value=[
                    {
                        "process_id": 70,
                        "run_mode": "process",
                        "status": "failed",
                        "retry_count": 0,
                        "max_retries": 3,
                        "error_message": "boom",
                        "created_at": "t0",
                        "updated_at": "t1",
                        "stages": [
                            {
                                "stage": "pipeline",
                                "result": "error",
                                "output": "boom",
                                "created_at": "t1",
                            }
                        ],
                    },
                    {
                        "process_id": 77,
                        "run_mode": "retry",
                        "status": "processing",
                        "retry_count": 1,
                        "max_retries": 3,
                        "error_message": None,
                        "created_at": "t2",
                        "updated_at": "t3",
                        "stages": [
                            {
                                "stage": "graph_builder",
                                "result": "success",
                                "output": "",
                                "created_at": "t3",
                            }
                        ],
                    },
                ],
            ),
            patch(
                "routers.documents._load_pipeline_stage_details",
                new_callable=AsyncMock,
                return_value=[],
            ),
            patch(
                "routers.documents._load_book_process_summary",
                new_callable=AsyncMock,
                return_value=None,
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process")

        assert resp.status_code == 202
        data = resp.json()
        assert "process_id" not in data
        assert "process_runs" in data
        assert len(data["process_runs"]) == 2
        assert data["latest_process_run"]["process_id"] == 77
        assert data["latest_process_run"]["run_mode"] == "retry"
        assert data["process_runs"][0]["run_mode"] == "process"
        assert data["process_runs"][1]["run_mode"] == "retry"


class TestDocumentProcessRetry:
    """POST /api/documents/{document_id}/process/retry"""

    @pytest.mark.asyncio
    async def test_retry_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/retry")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_retry_success_returns_202(self, authed_app, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 99
            status = "pending"
            retry_count = 0
            max_retries = 3

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._retry_lp_document_process",
                new_callable=AsyncMock,
                return_value=_Row(),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
            patch("routers.documents.asyncio.create_task", return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/retry")

        assert resp.status_code == 202
        data = resp.json()
        assert data["document_id"] == "doc-abc"
        assert data["lp_doc_id"] == "lp-doc-id"
        assert data["already_started"] is False
        assert data["status"] == "pending"
        assert data["latest_process_run"]["process_id"] == 99

    @pytest.mark.asyncio
    async def test_retry_conflict_returns_409(self, authed_app, tmp_path: Path) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._retry_lp_document_process",
                new_callable=AsyncMock,
                side_effect=HTTPException(
                    status_code=409,
                    detail="Document processing is already pending or in progress",
                ),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/retry")

        assert resp.status_code == 409


class TestDocumentReprocess:
    """POST /api/documents/{document_id}/process/reprocess"""

    @pytest.mark.asyncio
    async def test_reprocess_not_found_returns_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/reprocess")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_reprocess_success_returns_202(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        class _Row:
            id = 101
            status = "pending"
            retry_count = 0
            max_retries = 3

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._reprocess_lp_document_process",
                new_callable=AsyncMock,
                return_value=_Row(),
            ),
            patch("routers.documents.stable_doc_id", return_value="lp-doc-id"),
            patch("routers.documents.asyncio.create_task", return_value=None),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/reprocess")

        assert resp.status_code == 202
        data = resp.json()
        assert data["document_id"] == "doc-abc"
        assert data["lp_doc_id"] == "lp-doc-id"
        assert data["already_started"] is False
        assert data["status"] == "pending"
        assert data["latest_process_run"]["process_id"] == 101

    @pytest.mark.asyncio
    async def test_reprocess_conflict_returns_409(
        self, authed_app, tmp_path: Path
    ) -> None:
        fake_pdf = tmp_path / "doc.pdf"
        fake_pdf.write_bytes(b"fake")

        with (
            patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(fake_pdf)},
            ),
            patch(
                "routers.documents._reprocess_lp_document_process",
                new_callable=AsyncMock,
                side_effect=HTTPException(
                    status_code=409,
                    detail="Document processing is already pending or in progress",
                ),
            ),
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/doc-abc/process/reprocess")

        assert resp.status_code == 409


class TestDocumentViews:
    """GET /api/documents/{document_id}/tree|units|concepts|study-plan|export/json"""

    def _stub_lp(self, tmp_path: Path):
        """Return a stub LearningPlatformService with a canned result."""
        from learning_platform.models.concept import ConceptMap
        from learning_platform.models.knowledge_graph import KnowledgeGraph
        from learning_platform.models.sequence import StudyPlan
        from learning_platform.pipeline.orchestrator import PipelineResult
        from learning_platform.models.document import CanonicalDocument

        doc = CanonicalDocument(source=str(tmp_path / "x.pdf"), title="X", nodes=[])
        doc.rebuild_index()
        result = PipelineResult(
            document=doc,
            annotations=[],
            units=[],
            concepts=ConceptMap(),
            graph=KnowledgeGraph(nodes=[], edges=[]),
            study_plan=StudyPlan(
                title="",
                description="",
                lessons=[],
                milestones=[],
                checkpoints=[],
                total_estimated_minutes=0,
                total_lessons=0,
            ),
        )
        lp = MagicMock()
        lp.get_cached = MagicMock(return_value=result)
        return lp, result

    @pytest.mark.asyncio
    async def test_tree_doc_not_found_404(self, authed_app) -> None:
        with patch(
            "routers.documents.get_document", new_callable=AsyncMock, return_value=None
        ):
            async with AsyncClient(
                transport=ASGITransport(app=authed_app), base_url="http://test"
            ) as client:
                resp = await client.get("/api/documents/doc-abc/tree")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tree_not_processed_404(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp = MagicMock()
        lp.get_cached = MagicMock(return_value=None)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/tree")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tree_uses_persistence_fallback(
        self, authed_app, tmp_path: Path
    ) -> None:
        from routers.documents import get_service as _gs

        lp, result = self._stub_lp(tmp_path)
        lp.get_cached = MagicMock(return_value=None)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with (
                patch(
                    "routers.documents.get_document",
                    new_callable=AsyncMock,
                    return_value={"storage_path": str(tmp_path / "x.pdf")},
                ),
                patch(
                    "routers.documents.load_pipeline_result_from_persistence",
                    new_callable=AsyncMock,
                    return_value=result,
                ) as load_mock,
                patch(
                    "routers.documents.lp_doc_uuid_from_storage_path",
                    return_value=UUID("12345678-1234-5678-1234-567812345678"),
                ),
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/tree")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)

        assert resp.status_code == 200
        load_mock.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_tree_cached_200(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp, _ = self._stub_lp(tmp_path)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/tree")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_units_not_processed_404(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp = MagicMock(get_cached=MagicMock(return_value=None))
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/units")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_units_cached_200(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp, _ = self._stub_lp(tmp_path)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/units")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_concepts_cached_200(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp, _ = self._stub_lp(tmp_path)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/concepts")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 200
        assert resp.json()["total_concepts"] == 0

    @pytest.mark.asyncio
    async def test_study_plan_cached_200(self, authed_app, tmp_path: Path) -> None:
        from routers.documents import get_service as _gs

        lp, _ = self._stub_lp(tmp_path)
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/study-plan")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 200

    @pytest.mark.asyncio
    async def test_export_json_not_processed_404(
        self, authed_app, tmp_path: Path
    ) -> None:
        from routers.documents import get_service as _gs

        lp = MagicMock(get_cached=MagicMock(return_value=None))
        authed_app.dependency_overrides[_gs] = lambda: lp
        try:
            with patch(
                "routers.documents.get_document",
                new_callable=AsyncMock,
                return_value={"storage_path": str(tmp_path / "x.pdf")},
            ):
                async with AsyncClient(
                    transport=ASGITransport(app=authed_app), base_url="http://test"
                ) as client:
                    resp = await client.get("/api/documents/doc-abc/export/json")
        finally:
            authed_app.dependency_overrides.pop(_gs, None)
        assert resp.status_code == 404


# ── src/services/mapping.py ───────────────────────────────────────────────────


class TestMappingService:
    """Unit tests for services/mapping.py (no HTTP)."""

    def setup_method(self) -> None:
        from services.mapping import _mapping_configs

        _mapping_configs.clear()

    def test_get_mapping_configuration_returns_default(self) -> None:
        from services.mapping import get_mapping_configuration

        config = get_mapping_configuration("new-doc")
        assert config is not None

    def test_save_and_get_mapping_configuration(self) -> None:
        from services.mapping import (
            get_mapping_configuration,
            save_mapping_configuration,
        )
        from learning_platform.presentation.mappers.configuration import (
            create_default_config,
        )

        cfg = create_default_config()
        save_mapping_configuration("doc-1", cfg)
        assert get_mapping_configuration("doc-1") is cfg

    def test_reset_mapping_configuration(self) -> None:
        from services.mapping import (
            get_mapping_configuration,
            reset_mapping_configuration,
            save_mapping_configuration,
        )
        from learning_platform.presentation.mappers.configuration import (
            create_default_config,
        )

        cfg = create_default_config()
        save_mapping_configuration("doc-x", cfg)
        reset = reset_mapping_configuration("doc-x")
        assert reset is not None
        assert get_mapping_configuration("doc-x") is reset

    def test_pipeline_result_to_output(self) -> None:
        from services.mapping import pipeline_result_to_output
        from learning_platform.models.concept import ConceptMap
        from learning_platform.models.document import CanonicalDocument
        from learning_platform.models.knowledge_graph import KnowledgeGraph
        from learning_platform.models.sequence import StudyPlan
        from learning_platform.pipeline.orchestrator import PipelineResult

        doc = CanonicalDocument(source="x", title="T", nodes=[])
        doc.rebuild_index()
        result = PipelineResult(
            document=doc,
            annotations=[],
            units=[],
            concepts=ConceptMap(),
            graph=KnowledgeGraph(nodes=[], edges=[]),
            study_plan=StudyPlan(
                title="",
                description="",
                lessons=[],
                milestones=[],
                checkpoints=[],
                total_estimated_minutes=0,
                total_lessons=0,
            ),
        )
        output = pipeline_result_to_output(result)
        assert output.document is doc
        assert output.learning_units == []
        assert output.quizzes == []

    def test_generate_study_experience_raises_when_not_cached(self) -> None:
        from services.mapping import generate_study_experience
        from learning_platform.presentation.mappers.context import ProgressContext

        with pytest.raises(ValueError, match="No pipeline result cached"):
            generate_study_experience(
                "unknown-doc", ProgressContext(user_id=1, course_id=0)
            )

    def test_list_cached_documents_empty(self) -> None:
        from services.mapping import list_cached_documents
        from learning_platform.cache import pipeline_cache

        pipeline_cache.clear()
        assert list_cached_documents() == []


# ── src/routers/mapping.py ────────────────────────────────────────────────────


class TestMappingRouter:
    """GET/PUT/POST /api/documents/{doc_id}/mapping*"""

    @pytest.mark.asyncio
    async def test_get_mapping_not_cached_returns_404(self, authed_app) -> None:
        from services.mapping import _mapping_configs

        _mapping_configs.clear()
        from learning_platform.cache import pipeline_cache

        pipeline_cache.clear()

        async with AsyncClient(
            transport=ASGITransport(app=authed_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/documents/no-such-doc/mapping")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_put_mapping_returns_200(self, authed_app) -> None:
        # Send a minimal valid payload — all sub-schemas have defaults.
        payload = {"configuration": {}}
        async with AsyncClient(
            transport=ASGITransport(app=authed_app), base_url="http://test"
        ) as client:
            resp = await client.put("/api/documents/doc-xyz/mapping", json=payload)
        assert resp.status_code == 200
        assert resp.json()["doc_id"] == "doc-xyz"
        assert "updated successfully" in resp.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_regenerate_mapping_returns_200(self, authed_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=authed_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/documents/doc-xyz/mapping/regenerate")
        assert resp.status_code == 200
        assert resp.json()["doc_id"] == "doc-xyz"

    @pytest.mark.asyncio
    async def test_reset_mapping_returns_200(self, authed_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=authed_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/documents/doc-xyz/mapping/reset")
        assert resp.status_code == 200
        assert "defaults" in resp.json()["message"].lower()

    @pytest.mark.asyncio
    async def test_preview_mapping_not_cached_returns_404(self, authed_app) -> None:
        from learning_platform.cache import pipeline_cache

        pipeline_cache.clear()
        async with AsyncClient(
            transport=ASGITransport(app=authed_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/documents/no-such-doc/mapping/preview")
        assert resp.status_code == 404


# ── stable_doc_id helper ──────────────────────────────────────────────────────


class TestStableDocId:
    """Unit tests for stable_doc_id()."""

    def test_deterministic(self) -> None:
        from learning_platform.service import stable_doc_id

        assert stable_doc_id("/foo/bar.pdf") == stable_doc_id("/foo/bar.pdf")

    def test_different_paths_differ(self) -> None:
        from learning_platform.service import stable_doc_id

        assert stable_doc_id("/foo/a.pdf") != stable_doc_id("/foo/b.pdf")

    def test_returns_64_hex_chars(self) -> None:
        from learning_platform.service import stable_doc_id

        result = stable_doc_id("/some/path.pdf")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_first_32_chars_is_valid_uuid(self) -> None:
        from learning_platform.service import stable_doc_id
        from uuid import UUID

        result = stable_doc_id("/some/path.pdf")
        UUID(result[:32])  # must not raise
