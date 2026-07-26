"""Tests for the FastAPI API layer — health, documents, and courses endpoints."""

from __future__ import annotations

import io
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from learning_platform.api.app import create_app
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

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture()
def settings() -> Settings:
    """Minimal settings for test app."""
    return Settings(
        database_url="sqlite+aiosqlite:///:memory:",
        debug=True,
    )


@pytest.fixture()
def app(settings: Settings):
    """Create the FastAPI app with routes wired."""
    return create_app(settings)


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


_DOC_REPOS = [
    "learning_platform.api.routes.documents.DocumentRepository",
    "learning_platform.api.routes.documents.LearningUnitRepository",
    "learning_platform.api.routes.documents.AnnotationRepository",
    "learning_platform.api.routes.documents.ConceptRepository",
    "learning_platform.api.routes.documents.KnowledgeGraphRepository",
    "learning_platform.api.routes.documents.StudyPlanRepository",
]


def _patch_repos() -> list[object]:
    """Return a list of patch contexts for all document route repositories."""
    return [patch(path) for path in _DOC_REPOS]


# ══════════════════════════════════════════════════════════════════════════════
# Health endpoint
# ══════════════════════════════════════════════════════════════════════════════


class TestHealthEndpoint:
    """GET /health"""

    @pytest.mark.asyncio
    async def test_health_ok(self, app) -> None:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/health")

        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ══════════════════════════════════════════════════════════════════════════════
# Document Upload
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentUpload:
    """POST /api/documents/upload"""

    @pytest.mark.asyncio
    async def test_upload_returns_201(self, app, tmp_path: Path) -> None:
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
                    files={"file": ("test.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")},
                )

        assert resp.status_code == 201
        data = resp.json()
        UUID(data["doc_id"])
        assert data["filename"] == "test.pdf"

    @pytest.mark.asyncio
    async def test_upload_empty_content_type_succeeds(self, app, tmp_path: Path) -> None:
        """Upload with a generic content type still works as long as filename is set."""
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
                    files={
                        "file": (
                            "data.bin",
                            io.BytesIO(b"\x00\x01\x02"),
                            "application/octet-stream",
                        )
                    },
                )

        assert resp.status_code == 201
        assert resp.json()["filename"] == "data.bin"


# ══════════════════════════════════════════════════════════════════════════════
# Document Process
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentProcess:
    """POST /api/documents/{doc_id}/process"""

    @pytest.mark.asyncio
    async def test_process_success(self, app, tmp_path: Path) -> None:
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)

        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "test.pdf").write_bytes(b"fake")

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

            repo_patches = _patch_repos()
            mocks = [p.start() for p in repo_patches]
            for m in mocks:
                m.return_value = MagicMock(
                    save_document=AsyncMock(),
                    save_all_units=AsyncMock(),
                    save_all_annotations=AsyncMock(),
                    save_concept_map=AsyncMock(),
                    save_graph=AsyncMock(),
                    save_plan=AsyncMock(),
                )

            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(f"/api/documents/{doc_id}/process")
            finally:
                for p in repo_patches:
                    p.stop()

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
    async def test_process_missing_document_returns_404(self, app, tmp_path: Path) -> None:
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


# ══════════════════════════════════════════════════════════════════════════════
# Document Tree
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentTree:
    """GET /api/documents/{doc_id}/tree"""

    @pytest.mark.asyncio
    async def test_tree_from_cache(self, app, _clear_cache: None) -> None:
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
# Document Enrich
# ══════════════════════════════════════════════════════════════════════════════


class TestDocumentEnrich:
    """POST /api/documents/{doc_id}/enrich"""

    @pytest.mark.asyncio
    async def test_enrich_returns_cached_when_available(self, app, _clear_cache: None) -> None:
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        pipeline_cache.set(str(doc_id), result)

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.post(f"/api/documents/{doc_id}/enrich")

        assert resp.status_code == 200
        assert resp.json()["message"] == "Document already processed (cached result)"

    @pytest.mark.asyncio
    async def test_enrich_runs_pipeline_when_not_cached(self, app, tmp_path: Path) -> None:
        doc_id = uuid4()
        result = _make_pipeline_result(doc_id)
        upload_dir = tmp_path / "uploads" / str(doc_id)
        upload_dir.mkdir(parents=True)
        (upload_dir / "test.pdf").write_bytes(b"fake")

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

            repo_patches = _patch_repos()
            mocks = [p.start() for p in repo_patches]
            for m in mocks:
                m.return_value = MagicMock(
                    save_document=AsyncMock(),
                    save_all_units=AsyncMock(),
                    save_all_annotations=AsyncMock(),
                    save_concept_map=AsyncMock(),
                    save_graph=AsyncMock(),
                    save_plan=AsyncMock(),
                )

            try:
                async with AsyncClient(
                    transport=ASGITransport(app=app), base_url="http://test"
                ) as client:
                    resp = await client.post(f"/api/documents/{doc_id}/enrich")
            finally:
                for p in repo_patches:
                    p.stop()

        assert resp.status_code == 200
        assert resp.json()["units_count"] == 1


# ══════════════════════════════════════════════════════════════════════════════
# Learning Units
# ══════════════════════════════════════════════════════════════════════════════


class TestLearningUnits:
    """GET /api/documents/{doc_id}/units"""

    @pytest.mark.asyncio
    async def test_units_from_cache(self, app, _clear_cache: None) -> None:
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
# Concept Graph
# ══════════════════════════════════════════════════════════════════════════════


class TestConceptGraph:
    """GET /api/documents/{doc_id}/concepts"""

    @pytest.mark.asyncio
    async def test_concepts_from_cache(self, app, _clear_cache: None) -> None:
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
# Study Plan
# ══════════════════════════════════════════════════════════════════════════════


class TestStudyPlan:
    """GET /api/documents/{doc_id}/study-plan"""

    @pytest.mark.asyncio
    async def test_study_plan_from_cache(self, app, _clear_cache: None) -> None:
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
# JSON Export
# ══════════════════════════════════════════════════════════════════════════════


class TestJsonExport:
    """GET /api/documents/{doc_id}/export/json"""

    @pytest.mark.asyncio
    async def test_export_json_from_cache(self, app, _clear_cache: None, tmp_path: Path) -> None:
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
        doc_id = uuid4()

        app.dependency_overrides[get_session] = _mock_get_session

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get(f"/api/documents/{doc_id}/export/json")

        assert resp.status_code == 404


# ══════════════════════════════════════════════════════════════════════════════
# Courses
# ══════════════════════════════════════════════════════════════════════════════


class TestCoursesEndpoint:
    """GET /api/courses/"""

    @pytest.mark.asyncio
    async def test_list_courses_empty(self, app) -> None:
        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            mock_session = AsyncMock()
            mock_result = MagicMock()
            mock_result.scalars.return_value.all.return_value = []
            mock_session.execute = AsyncMock(return_value=mock_result)
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/courses/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["courses"] == []
        assert data["count"] == 0

    @pytest.mark.asyncio
    async def test_list_courses_with_data(self, app) -> None:
        mock_row = MagicMock()
        mock_row.id = uuid4()
        mock_row.title = "Python 101"
        mock_row.description = "Learn Python"

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_row]

        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(return_value=mock_result)
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/courses/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 1
        assert data["courses"][0]["title"] == "Python 101"
        assert data["courses"][0]["description"] == "Learn Python"

    @pytest.mark.asyncio
    async def test_list_courses_db_error_returns_empty(self, app) -> None:
        async def _mock_session_gen() -> AsyncGenerator[AsyncMock, None]:
            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(side_effect=RuntimeError("DB down"))
            yield mock_session

        app.dependency_overrides[get_session] = _mock_session_gen

        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            resp = await client.get("/api/courses/")

        assert resp.status_code == 200
        data = resp.json()
        assert data["courses"] == []
        assert data["count"] == 0
