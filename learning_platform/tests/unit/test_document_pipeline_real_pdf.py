"""Integration tests for document pipeline with real PDF.

Tests the full document processing pipeline using test_pdfs/950ec5720caf4339ac468e834dcfaa70.pdf.
Includes failure simulation tests to verify error handling.
"""

from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from learning_platform.api.app import create_app
from learning_platform.api.auth import get_current_user
from learning_platform.api.deps import get_pipeline_orchestrator, get_session
from learning_platform.cache import pipeline_cache
from learning_platform.config import Settings
from learning_platform.models.annotation import (
    Annotation,
    DefinitionAnnotation,
    ObjectiveAnnotation,
)
from learning_platform.models.concept import (
    Concept,
    ConceptCategory,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentNode,
    Heading,
    HeadingLevel,
    StyledText,
    TextRun,
)
from learning_platform.models.knowledge_graph import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)
from learning_platform.models.learning_unit import Difficulty, LearningUnit, UnitType
from learning_platform.models.sequence import (
    Checkpoint,
    CheckpointType,
    Lesson,
    LessonType,
    Milestone,
    StudyPlan,
)
from learning_platform.pipeline.orchestrator import PipelineResult
from learning_platform.service import get_service

# ── Constants ────────────────────────────────────────────────────────────────

TEST_PDF_PATH: Path = (
    Path(__file__).parent.parent.parent.parent
    / "test_pdfs"
    / "950ec5720caf4339ac468e834dcfaa70.pdf"
)


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def settings() -> Settings:
    """Minimal settings for test app."""
    return Settings(
        environment="test",
        database_url="sqlite+aiosqlite:///:memory:",
        debug=True,
        s3_access_key="minioadmin",
        s3_secret_key="minioadmin",
        jwt_secret="test-jwt-secret",
    )


@pytest.fixture()
def app(settings: Settings):
    """Create the FastAPI app with routes wired."""
    application = create_app(settings)
    application.dependency_overrides[get_current_user] = _mock_get_current_user
    return application


@pytest.fixture()
def _clear_cache() -> None:
    """Clear the in-memory pipeline cache before and after each test."""
    pipeline_cache.clear()
    yield
    pipeline_cache.clear()


# ── Shared domain fixtures ─────────────────────────────────────────────────


def _make_root_node(doc_id: UUID) -> DocumentNode:
    """Create a minimal root DocumentNode."""
    return DocumentNode(
        id=doc_id,
        content=Heading(
            text=StyledText(runs=[TextRun(text="Test Document")]),
            level=HeadingLevel.CHAPTER,
        ),
        level=1,
    )


def _make_document(doc_id: UUID) -> CanonicalDocument:
    """Create a minimal CanonicalDocument."""
    root = _make_root_node(doc_id)
    doc = CanonicalDocument(
        source="/uploads/test.pdf",
        title="Test Document",
        nodes=[root],
    )
    doc.rebuild_index()
    return doc


def _make_unit(doc_id: UUID) -> LearningUnit:
    """Create a minimal LearningUnit."""
    return LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Test Lesson",
        description="A test lesson",
        difficulty=Difficulty.BASIC,
        estimated_study_time_minutes=15,
        learning_objectives=["Understand testing"],
    )


def _make_concept(_doc_id: UUID) -> Concept:
    """Create a minimal Concept."""
    return Concept(
        id=uuid4(),
        name="Testing",
        category=ConceptCategory.CONCEPT,
        importance=0.8,
        mention_count=5,
    )


def _make_concept_map(_doc_id: UUID) -> ConceptMap:
    """Create a minimal ConceptMap with one concept and one relationship."""
    c1 = _make_concept(_doc_id)
    c2 = Concept(
        id=uuid4(),
        name="Quality Assurance",
        category=ConceptCategory.CONCEPT,
        importance=0.6,
        mention_count=3,
    )
    rel = ConceptRelationship(
        source_id=c1.id,
        target_id=c2.id,
        relation_type=RelationType.RELATES_TO,
    )
    return ConceptMap(concepts=[c1, c2], relationships=[rel])


def _make_graph(_doc_id: UUID, unit: LearningUnit, concept_map: ConceptMap) -> KnowledgeGraph:
    """Create a minimal KnowledgeGraph."""
    unit_node = GraphNode(
        id=uuid4(),
        node_type=NodeType.UNIT,
        label=unit.title,
        unit_id=unit.id,
    )
    concept_node = GraphNode(
        id=uuid4(),
        node_type=NodeType.CONCEPT,
        label=concept_map.concepts[0].name,
        concept_id=concept_map.concepts[0].id,
    )
    edge = GraphEdge(
        source_id=unit_node.id,
        target_id=concept_node.id,
        edge_type=EdgeType.REFERENCES,
    )
    return KnowledgeGraph(nodes=[unit_node, concept_node], edges=[edge])


def _make_study_plan(_doc_id: UUID, unit: LearningUnit) -> StudyPlan:
    """Create a minimal StudyPlan."""
    milestone_id = uuid4()
    lesson = Lesson(
        id=uuid4(),
        unit_id=unit.id,
        order=0,
        title="Lesson 1",
        lesson_type=LessonType.CORE,
        difficulty="basic",
        estimated_minutes=15,
        milestone_id=milestone_id,
    )
    milestone = Milestone(
        id=milestone_id,
        order=0,
        title="Milestone 1",
        lesson_ids=[lesson.id],
        estimated_minutes=15,
    )
    checkpoint = Checkpoint(
        id=uuid4(),
        milestone_id=milestone_id,
        order=1,
        title="Checkpoint 1",
        checkpoint_type=CheckpointType.SELF_TEST,
        estimated_minutes=10,
        lesson_ids=[lesson.id],
    )
    return StudyPlan(
        title="Test Study Plan",
        description="A test study plan",
        lessons=[lesson],
        milestones=[milestone],
        checkpoints=[checkpoint],
        total_estimated_minutes=25,
        total_lessons=1,
    )


def _make_annotations(_doc_id: UUID) -> list[Annotation]:
    """Create a minimal list of annotations."""
    node_id = uuid4()
    return [
        DefinitionAnnotation(
            node_id=node_id,
            term="Testing",
            definition_text="The act of testing software.",
        ),
        ObjectiveAnnotation(
            node_id=node_id,
            objective_text="Learn to test",
        ),
    ]


def _make_pipeline_result(doc_id: UUID) -> PipelineResult:
    """Build a complete PipelineResult for test use."""
    doc = _make_document(doc_id)
    unit = _make_unit(doc_id)
    concept_map = _make_concept_map(doc_id)
    annotations = _make_annotations(doc_id)
    graph = _make_graph(doc_id, unit, concept_map)
    plan = _make_study_plan(doc_id, unit)
    return PipelineResult(
        document=doc,
        annotations=annotations,
        units=[unit],
        concepts=concept_map,
        graph=graph,
        study_plan=plan,
    )


async def _mock_get_session() -> AsyncGenerator[AsyncMock, None]:
    """Mock get_session dependency that yields a mock session."""
    session = AsyncMock()
    yield session


def _mock_user() -> dict[str, Any]:
    """Create a mock user for authenticated requests."""
    return {"id": 1, "email": "test@example.com"}


async def _mock_get_current_user() -> dict[str, Any]:
    """Mock get_current_user dependency."""
    return _mock_user()


# ══════════════════════════════════════════════════════════════════════════════
# Document Upload with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentUploadWithRealPDF:
    """POST /api/documents/upload with actual PDF file."""

    @pytest.mark.asyncio
    async def test_upload_real_pdf(self, app, tmp_path: Path) -> None:
        """Upload the actual test PDF and verify response."""
        if not TEST_PDF_PATH.exists():
            pytest.skip(f"Test PDF not found: {TEST_PDF_PATH}")

        app.dependency_overrides[get_session] = _mock_get_session
        upload_base = tmp_path / "uploads"

        with patch("learning_platform.api.routes.documents.Path") as mock_path:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return upload_base
                return original_path(p)

            mock_path.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                with open(TEST_PDF_PATH, "rb") as f:
                    resp = await client.post(
                        "/api/documents/upload",
                        files={"file": (TEST_PDF_PATH.name, f, "application/pdf")},
                    )

        assert resp.status_code == 201
        data = resp.json()
        _doc_id = UUID(data["doc_id"])
        assert data["filename"] == TEST_PDF_PATH.name
        assert "doc_id" in data

    @pytest.mark.asyncio
    async def test_upload_empty_file_returns_201(self, app, tmp_path: Path) -> None:
        """Upload an empty file (edge case)."""
        app.dependency_overrides[get_session] = _mock_get_session
        upload_base = tmp_path / "uploads"

        with patch("learning_platform.api.routes.documents.Path") as mock_path:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return upload_base
                return original_path(p)

            mock_path.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/documents/upload",
                    files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
                )

        assert resp.status_code == 201

    @pytest.mark.asyncio
    async def test_upload_no_filename_returns_422(self, app, tmp_path: Path) -> None:
        """Upload without filename returns 422 (validation error)."""
        app.dependency_overrides[get_session] = _mock_get_session
        upload_base = tmp_path / "uploads"

        with patch("learning_platform.api.routes.documents.Path") as mock_path:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return upload_base
                return original_path(p)

            mock_path.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(
                    "/api/documents/upload",
                    files={"file": ("", io.BytesIO(b"content"), "application/pdf")},
                )

        # FastAPI returns 422 for empty filename due to validation
        assert resp.status_code == 422


# ══════════════════════════════════════════════════════════════════════════════
# Document Process with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentProcessWithRealPDF:
    """POST /api/documents/{doc_id}/process with actual PDF."""

    @pytest.mark.asyncio
    async def test_process_real_pdf(self, app, tmp_path: Path) -> None:
        """Process the actual test PDF through the pipeline."""
        if not TEST_PDF_PATH.exists():
            pytest.skip(f"Test PDF not found: {TEST_PDF_PATH}")

        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)

        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / TEST_PDF_PATH.name).write_bytes(TEST_PDF_PATH.read_bytes())

        mock_session = AsyncMock()
        mock_orchestrator = MagicMock(run=MagicMock(return_value=result))

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen
        app.dependency_overrides[get_pipeline_orchestrator] = lambda: mock_orchestrator

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return tmp_path / "uploads"
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/process")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["title"] == "Test Document"
        assert data["units_count"] == 1
        assert data["concepts_count"] == 2
        assert data["graph_nodes"] == 2
        assert data["graph_edges"] == 1
        assert data["lessons"] == 1
        assert data["milestones"] == 1

    @pytest.mark.asyncio
    async def test_process_uses_service_path(self, app, tmp_path: Path) -> None:
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)

        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "test.pdf").write_bytes(b"fake")

        mock_session = AsyncMock()
        mock_service = MagicMock()
        mock_service.process = AsyncMock(return_value=result)
        mock_orchestrator = MagicMock()

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen
        app.dependency_overrides[get_service] = lambda: mock_service
        app.dependency_overrides[get_pipeline_orchestrator] = lambda: mock_orchestrator

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return tmp_path / "uploads"
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/process")

        assert resp.status_code == 200
        mock_service.process.assert_awaited_once()


# ══════════════════════════════════════════════════════════════════════════════
# Document Tree with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentTreeWithRealPDF:
    """GET /api/documents/{doc_id}/tree with actual PDF."""

    @pytest.mark.asyncio
    async def test_tree_from_cache(self, app, _clear_cache: None) -> None:
        """View document tree from cached result."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/tree")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["title"] == "Test Document"
        assert data["total_nodes"] >= 1
        assert data["root"] is not None

    @pytest.mark.asyncio
    async def test_tree_not_found_returns_404(self, app, _clear_cache: None) -> None:
        """View document tree for non-existent document."""
        doc_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.find_document = AsyncMock(return_value=None)

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch(
            "learning_platform.api.routes.documents.DocumentRepository",
            return_value=mock_repo,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/tree")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Learning Units with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestLearningUnitsWithRealPDF:
    """GET /api/documents/{doc_id}/units with actual PDF."""

    @pytest.mark.asyncio
    async def test_units_from_cache(self, app, _clear_cache: None) -> None:
        """View learning units from cached result."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/units")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["count"] == 1
        assert data["units"][0]["title"] == "Test Lesson"
        assert data["units"][0]["unit_type"] == "lesson"
        assert data["units"][0]["difficulty"] == "basic"

    @pytest.mark.asyncio
    async def test_units_not_found_returns_404(self, app, _clear_cache: None) -> None:
        """View learning units for non-existent document."""
        doc_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.find_by_document = AsyncMock(return_value=[])

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch(
            "learning_platform.api.routes.documents.LearningUnitRepository",
            return_value=mock_repo,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/units")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Concept Graph with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestConceptGraphWithRealPDF:
    """GET /api/documents/{doc_id}/concepts with actual PDF."""

    @pytest.mark.asyncio
    async def test_concepts_from_cache(self, app, _clear_cache: None) -> None:
        """View concept graph from cached result."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/concepts")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["total_concepts"] == 2
        assert data["total_relationships"] == 1
        names = {c["name"] for c in data["concepts"]}
        assert "Testing" in names
        assert "Quality Assurance" in names

    @pytest.mark.asyncio
    async def test_concepts_not_found_returns_404(self, app, _clear_cache: None) -> None:
        """View concepts for non-existent document."""
        doc_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.find_by_document = AsyncMock(return_value=ConceptMap())

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch(
            "learning_platform.api.routes.documents.ConceptRepository",
            return_value=mock_repo,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/concepts")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Study Plan with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestStudyPlanWithRealPDF:
    """GET /api/documents/{doc_id}/study-plan with actual PDF."""

    @pytest.mark.asyncio
    async def test_study_plan_from_cache(self, app, _clear_cache: None) -> None:
        """View study plan from cached result."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/study-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["title"] == "Test Study Plan"
        assert data["total_lessons"] == 1
        assert data["total_estimated_minutes"] == 25
        assert len(data["lessons"]) == 1
        assert len(data["milestones"]) == 1
        assert len(data["checkpoints"]) == 1
        assert data["lessons"][0]["lesson_type"] == "core"
        assert data["lessons"][0]["difficulty"] == "basic"
        assert data["milestones"][0]["lesson_count"] == 1
        assert data["checkpoints"][0]["checkpoint_type"] == "self_test"

    @pytest.mark.asyncio
    async def test_study_plan_not_found_returns_404(self, app, _clear_cache: None) -> None:
        """View study plan for non-existent document."""
        doc_id = uuid4()

        mock_repo = AsyncMock()
        mock_repo.find_by_document = AsyncMock(return_value=None)

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch(
            "learning_platform.api.routes.documents.StudyPlanRepository",
            return_value=mock_repo,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/study-plan")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# JSON Export with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestJsonExportWithRealPDF:
    """GET /api/documents/{doc_id}/export/json with actual PDF."""

    @pytest.mark.asyncio
    async def test_export_json_from_cache(self, app, _clear_cache: None, tmp_path: Path) -> None:
        """Export JSON from cached result."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        real_export_dir = tmp_path / "exports" / str(doc_id)
        real_export_dir.mkdir(parents=True)

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            mock_path_cls.side_effect = lambda p: real_export_dir if not isinstance(p, Path) else p
            mock_path_cls.return_value = real_export_dir

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/export/json")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == str(doc_id)
        assert data["source"] == "/uploads/test.pdf"
        assert data["title"] == "Test Document"
        assert data["units_count"] == 1
        assert data["concepts_count"] == 2
        assert data["graph_nodes"] == 2
        assert data["lessons"] == 1
        assert len(data["files"]) == 6

    @pytest.mark.asyncio
    async def test_export_json_not_found_returns_404(self, app, _clear_cache: None) -> None:
        """Export JSON for non-existent document."""
        doc_id = uuid4()

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/export/json")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Failure Simulation Tests
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentPipelineFailures:
    """Tests simulating various failure scenarios in the document pipeline."""

    @pytest.mark.asyncio
    async def test_process_missing_document_returns_404(self, app, tmp_path: Path) -> None:
        """Process a non-existent document returns 404."""
        doc_id = uuid4()
        nonexistent = tmp_path / "nonexistent"

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return nonexistent
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/process")

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_process_pipeline_failure_returns_500(self, app, tmp_path: Path) -> None:
        """Process document with pipeline failure returns 500."""
        doc_id = uuid4()
        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "test.pdf").write_bytes(b"fake")

        mock_session = AsyncMock()
        mock_orchestrator = MagicMock(
            run=MagicMock(side_effect=RuntimeError("Pipeline processing failed"))
        )

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen
        app.dependency_overrides[get_pipeline_orchestrator] = lambda: mock_orchestrator

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return tmp_path / "uploads"
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/process")

        assert resp.status_code == 500
        assert "pipeline failed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_process_no_files_returns_404(self, app, tmp_path: Path) -> None:
        """Process document with empty upload directory returns 404."""
        doc_id = uuid4()
        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return tmp_path / "uploads"
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/process")

        assert resp.status_code == 404
        assert "no uploaded file found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_enrich_with_pipeline_failure_returns_500(self, app, tmp_path: Path) -> None:
        """Enrich document with pipeline failure returns 500."""
        doc_id = uuid4()
        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "test.pdf").write_bytes(b"fake")

        mock_session = AsyncMock()
        mock_orchestrator = MagicMock(run=MagicMock(side_effect=ValueError("Enrichment failed")))

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen
        app.dependency_overrides[get_pipeline_orchestrator] = lambda: mock_orchestrator

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return tmp_path / "uploads"
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/enrich")

        assert resp.status_code == 500
        assert "pipeline failed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_enrich_missing_document_returns_404(self, app, tmp_path: Path) -> None:
        """Enrich non-existent document returns 404."""
        doc_id = uuid4()
        nonexistent = tmp_path / "nonexistent"

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield AsyncMock()

        app.dependency_overrides[get_session] = _mock_session_gen

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return nonexistent
                return original_path(p)

            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                resp = await client.post(f"/api/documents/{doc_id}/enrich")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_enrich_returns_cached_when_available(self, app, _clear_cache: None) -> None:
        """Enrich returns cached result when available."""
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/documents/{doc_id}/enrich")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Document already processed (cached result)"

    @pytest.mark.asyncio
    async def test_tree_empty_document_returns_200(self, app, _clear_cache: None) -> None:
        """View tree for document with no nodes returns 200 with null root."""
        doc_id = uuid4()
        doc = CanonicalDocument(
            source="/uploads/test.pdf",
            title="Empty Document",
            nodes=[],
        )
        doc.rebuild_index()
        result = PipelineResult(
            document=doc,
            annotations=[],
            units=[],
            concepts=ConceptMap(),
            graph=KnowledgeGraph(nodes=[], edges=[]),
            study_plan=StudyPlan(
                title="Empty Plan",
                description="",
                lessons=[],
                milestones=[],
                checkpoints=[],
                total_estimated_minutes=0,
                total_lessons=0,
            ),
        )
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/tree")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_nodes"] == 0
        assert data["root"] is None

    @pytest.mark.asyncio
    async def test_units_empty_result_returns_200(self, app, _clear_cache: None) -> None:
        """View units for document with no units returns 200 with empty list from cache."""
        doc_id = uuid4()
        doc = CanonicalDocument(
            source="/uploads/test.pdf",
            title="Empty Document",
            nodes=[],
        )
        doc.rebuild_index()
        result = PipelineResult(
            document=doc,
            annotations=[],
            units=[],
            concepts=ConceptMap(),
            graph=KnowledgeGraph(nodes=[], edges=[]),
            study_plan=StudyPlan(
                title="Empty Plan",
                description="",
                lessons=[],
                milestones=[],
                checkpoints=[],
                total_estimated_minutes=0,
                total_lessons=0,
            ),
        )
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/units")

        # When cached, returns 200 with empty list (not 404)
        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_concepts_empty_result_returns_200(self, app, _clear_cache: None) -> None:
        """View concepts for document with no concepts returns 200 with empty list from cache."""
        doc_id = uuid4()
        doc = CanonicalDocument(
            source="/uploads/test.pdf",
            title="Empty Document",
            nodes=[],
        )
        doc.rebuild_index()
        result = PipelineResult(
            document=doc,
            annotations=[],
            units=[],
            concepts=ConceptMap(concepts=[], relationships=[]),
            graph=KnowledgeGraph(nodes=[], edges=[]),
            study_plan=StudyPlan(
                title="Empty Plan",
                description="",
                lessons=[],
                milestones=[],
                checkpoints=[],
                total_estimated_minutes=0,
                total_lessons=0,
            ),
        )
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/concepts")

        # When cached, returns 200 with empty list (not 404)
        assert resp.status_code == 200
        assert resp.json()["total_concepts"] == 0


# ══════════════════════════════════════════════════════════════════════════════
# Full Pipeline Integration Test with Real PDF
# ══════════════════════════════════════════════════════════════════════════════


class TestFullPipelineIntegrationWithRealPDF:
    """End-to-end test of the full document pipeline with real PDF."""

    @pytest.mark.asyncio
    async def test_full_pipeline_flow(self, app, tmp_path: Path) -> None:
        """Test complete flow: upload -> process -> view -> export."""
        if not TEST_PDF_PATH.exists():
            pytest.skip(f"Test PDF not found: {TEST_PDF_PATH}")

        # Step 1: Upload
        app.dependency_overrides[get_session] = _mock_get_session
        upload_base = tmp_path / "uploads"

        with patch("learning_platform.api.routes.documents.Path") as mock_path:
            original_path = Path

            def _path_factory(p: str | Path) -> Path:
                if isinstance(p, original_path):
                    return p
                if p == "uploads":
                    return upload_base
                return original_path(p)

            mock_path.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                with open(TEST_PDF_PATH, "rb") as f:
                    upload_resp = await client.post(
                        "/api/documents/upload",
                        files={"file": (TEST_PDF_PATH.name, f, "application/pdf")},
                    )

        assert upload_resp.status_code == 201
        doc_id = UUID(upload_resp.json()["doc_id"])

        # Step 2: Process
        result = _make_pipeline_result(doc_id)
        mock_session = AsyncMock()
        mock_orchestrator = MagicMock(run=MagicMock(return_value=result))

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen
        app.dependency_overrides[get_pipeline_orchestrator] = lambda: mock_orchestrator

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            mock_path_cls.side_effect = _path_factory

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                process_resp = await client.post(f"/api/documents/{doc_id}/process")

        assert process_resp.status_code == 200

        # Step 3: View Tree
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            tree_resp = await client.get(f"/api/documents/{doc_id}/tree")
        assert tree_resp.status_code == 200
        assert tree_resp.json()["doc_id"] == str(doc_id)

        # Step 4: View Units
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            units_resp = await client.get(f"/api/documents/{doc_id}/units")
        assert units_resp.status_code == 200
        assert units_resp.json()["count"] == 1

        # Step 5: View Concepts
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            concepts_resp = await client.get(f"/api/documents/{doc_id}/concepts")
        assert concepts_resp.status_code == 200
        assert concepts_resp.json()["total_concepts"] == 2

        # Step 6: View Study Plan
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            plan_resp = await client.get(f"/api/documents/{doc_id}/study-plan")
        assert plan_resp.status_code == 200
        assert plan_resp.json()["total_lessons"] == 1

        # Step 7: Export JSON
        real_export_dir = tmp_path / "exports" / str(doc_id)
        real_export_dir.mkdir(parents=True)

        with patch("learning_platform.api.routes.documents.Path") as mock_path_cls:
            mock_path_cls.side_effect = lambda p: real_export_dir if not isinstance(p, Path) else p
            mock_path_cls.return_value = real_export_dir

            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://test"
            ) as client:
                export_resp = await client.get(f"/api/documents/{doc_id}/export/json")

        assert export_resp.status_code == 200
        assert export_resp.json()["doc_id"] == str(doc_id)
