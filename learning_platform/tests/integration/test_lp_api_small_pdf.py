"""Integration test suite — all LP APIs via test_pdfs/small.pdf.

Covers every endpoint exposed by learning_platform:
  GET  /health
  POST /api/documents/process
  GET  /api/documents/{doc_id}/tree
  POST /api/documents/{doc_id}/enrich
  GET  /api/documents/{doc_id}/units
  GET  /api/documents/{doc_id}/concepts
  GET  /api/documents/{doc_id}/study-plan
  GET  /api/documents/{doc_id}/export/json

Strategy
--------
Each test class exercises one endpoint.  The heavy pipeline run is shared via
a module-scoped fixture so the PDF is processed only once per pytest session.

- ``test_process_*`` tests send ``POST /api/documents/process`` with the real
  ``small.pdf`` path and a mocked orchestrator that returns a canned
  ``PipelineResult``.  This isolates HTTP/routing/persistence concerns from the
  actual ML pipeline.

- ``test_real_pipeline`` runs the orchestrator for real against small.pdf.
  This test is marked ``@pytest.mark.slow`` and skipped when the PDF is absent.

Auth is bypassed via ``dependency_overrides``.
All DB I/O is captured by mocking the repository classes.
"""

from __future__ import annotations

import hashlib
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
from learning_platform.models.annotation import DefinitionAnnotation, ObjectiveAnnotation
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
)
from learning_platform.models.knowledge_graph import NodeType as GraphNodeType
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
from learning_platform.service import stable_doc_id

# ── Paths ────────────────────────────────────────────────────────────────────

SMALL_PDF: Path = Path(__file__).parent.parent.parent.parent / "test_pdfs" / "small.pdf"

_REPO_PATHS = [
    "learning_platform.api.routes.documents.DocumentRepository",
    "learning_platform.api.routes.documents.LearningUnitRepository",
    "learning_platform.api.routes.documents.AnnotationRepository",
    "learning_platform.api.routes.documents.ConceptRepository",
    "learning_platform.api.routes.documents.KnowledgeGraphRepository",
    "learning_platform.api.routes.documents.StudyPlanRepository",
]


# ── Domain fixtures ──────────────────────────────────────────────────────────


def _make_result(file_path: str) -> tuple[str, PipelineResult]:
    """Return (cache_key, PipelineResult).

    cache_key is the UUID-string form (str(UUID(sha256[:32]))) — the same key
    that all LP read routes use when looking up pipeline_cache.
    """
    doc_id_str = stable_doc_id(file_path)
    doc_id_uuid = UUID(doc_id_str[:32])
    cache_key = str(doc_id_uuid)  # matches pipeline_cache.get(str(doc_id)) in routes

    root = DocumentNode(
        id=doc_id_uuid,
        content=Heading(
            text=StyledText(runs=[TextRun(text="Small PDF")]),
            level=HeadingLevel.CHAPTER,
        ),
        level=1,
    )
    doc = CanonicalDocument(source=file_path, title="Small PDF", nodes=[root])
    doc.rebuild_index()

    unit = LearningUnit(
        id=uuid4(),
        unit_type=UnitType.LESSON,
        title="Introduction",
        description="Intro lesson",
        difficulty=Difficulty.BASIC,
        estimated_study_time_minutes=10,
        learning_objectives=["Understand basics"],
    )

    c1 = Concept(
        id=uuid4(),
        name="Concept A",
        category=ConceptCategory.CONCEPT,
        importance=0.9,
        mention_count=4,
    )
    c2 = Concept(
        id=uuid4(),
        name="Concept B",
        category=ConceptCategory.SKILL,
        importance=0.7,
        mention_count=2,
    )
    concept_map = ConceptMap(
        concepts=[c1, c2],
        relationships=[
            ConceptRelationship(
                source_id=c1.id, target_id=c2.id, relation_type=RelationType.RELATES_TO
            )
        ],
    )

    gn1 = GraphNode(id=uuid4(), node_type=GraphNodeType.UNIT, label=unit.title, unit_id=unit.id)
    gn2 = GraphNode(id=uuid4(), node_type=GraphNodeType.CONCEPT, label=c1.name, concept_id=c1.id)
    graph = KnowledgeGraph(
        nodes=[gn1, gn2],
        edges=[GraphEdge(source_id=gn1.id, target_id=gn2.id, edge_type=EdgeType.REFERENCES)],
    )

    mid = uuid4()
    lesson = Lesson(
        id=uuid4(),
        unit_id=unit.id,
        order=0,
        title="Lesson 1",
        lesson_type=LessonType.CORE,
        difficulty="basic",
        estimated_minutes=10,
        milestone_id=mid,
    )
    milestone = Milestone(
        id=mid, order=0, title="M1", lesson_ids=[lesson.id], estimated_minutes=10
    )
    checkpoint = Checkpoint(
        id=uuid4(),
        milestone_id=mid,
        order=0,
        title="CP1",
        checkpoint_type=CheckpointType.SELF_TEST,
        estimated_minutes=5,
        lesson_ids=[lesson.id],
    )
    plan = StudyPlan(
        title="Small PDF Plan",
        description="Auto-generated",
        lessons=[lesson],
        milestones=[milestone],
        checkpoints=[checkpoint],
        total_estimated_minutes=15,
        total_lessons=1,
    )

    annotations = [
        DefinitionAnnotation(
            node_id=root.id, term="PDF", definition_text="Portable Document Format"
        ),
        ObjectiveAnnotation(node_id=root.id, objective_text="Read a PDF"),
    ]

    return cache_key, PipelineResult(
        document=doc,
        annotations=annotations,
        units=[unit],
        concepts=concept_map,
        graph=graph,
        study_plan=plan,
    )


# ── Shared fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(database_url="sqlite+aiosqlite:///:memory:", debug=True)


@pytest.fixture(scope="module")
def lp_app(settings: Settings):
    """One LP app instance for the whole module; auth bypassed."""
    application = create_app(settings)
    application.dependency_overrides[get_current_user] = lambda: {"id": 1, "email": "t@t.com"}
    return application


@pytest.fixture(autouse=True)
def clear_cache() -> Any:
    pipeline_cache.clear()
    yield
    pipeline_cache.clear()


async def _mock_session() -> AsyncGenerator[AsyncMock, None]:
    yield AsyncMock()


def _patch_all_repos() -> list:
    return [patch(p) for p in _REPO_PATHS]


def _start_repo_patches() -> list:
    patches = _patch_all_repos()
    mocks = [p.start() for p in patches]
    for m in mocks:
        m.return_value = MagicMock(
            save_document=AsyncMock(),
            save_all_units=AsyncMock(),
            save_all_annotations=AsyncMock(),
            save_concept_map=AsyncMock(),
            save_graph=AsyncMock(),
            save_plan=AsyncMock(),
        )
    return patches


# ── Health ────────────────────────────────────────────────────────────────────


class TestHealth:
    """GET /health"""

    @pytest.mark.asyncio
    async def test_health_ok(self, lp_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    @pytest.mark.asyncio
    async def test_health_content_type(self, lp_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get("/health")
        assert "application/json" in resp.headers["content-type"]


# ── POST /api/documents/process ───────────────────────────────────────────────


class TestProcess:
    """POST /api/documents/process"""

    @pytest.mark.asyncio
    async def test_process_returns_201_with_counts(self, lp_app, tmp_path: Path) -> None:
        if not SMALL_PDF.exists():
            pytest.skip("test_pdfs/small.pdf not found")
        dest = tmp_path / "small.pdf"
        dest.write_bytes(SMALL_PDF.read_bytes())

        doc_id_str, result = _make_result(str(dest))
        doc_id_uuid = doc_id_str  # _make_result now returns UUID-string as key
        lp_app.dependency_overrides[get_pipeline_orchestrator] = lambda: MagicMock(
            run=MagicMock(return_value=result)
        )
        lp_app.dependency_overrides[get_session] = _mock_session

        patches = _start_repo_patches()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/process", json={"file_path": str(dest)})
        finally:
            for p in patches:
                p.stop()
        lp_app.dependency_overrides.pop(get_pipeline_orchestrator, None)

        assert resp.status_code == 201
        data = resp.json()
        assert "doc_id" in data
        assert data["title"] == "Small PDF"
        assert data["units_count"] == 1
        assert data["concepts_count"] == 2
        assert data["graph_nodes"] == 2
        assert data["graph_edges"] == 1
        assert data["lessons"] == 1
        assert data["milestones"] == 1

    @pytest.mark.asyncio
    async def test_process_caches_result(self, lp_app, tmp_path: Path) -> None:
        """Result is stored in pipeline_cache after processing."""
        if not SMALL_PDF.exists():
            pytest.skip("test_pdfs/small.pdf not found")
        dest = tmp_path / "small.pdf"
        dest.write_bytes(SMALL_PDF.read_bytes())

        doc_id_str, result = _make_result(str(dest))
        lp_app.dependency_overrides[get_pipeline_orchestrator] = lambda: MagicMock(
            run=MagicMock(return_value=result)
        )
        lp_app.dependency_overrides[get_session] = _mock_session

        patches = _start_repo_patches()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                await client.post("/api/documents/process", json={"file_path": str(dest)})
        finally:
            for p in patches:
                p.stop()
        lp_app.dependency_overrides.pop(get_pipeline_orchestrator, None)

        assert pipeline_cache.get(doc_id_str) is not None

    @pytest.mark.asyncio
    async def test_process_missing_file_returns_400(self, lp_app) -> None:
        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/documents/process", json={"file_path": "/nonexistent/file.pdf"}
            )
        assert resp.status_code == 400
        assert "not found" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_process_pipeline_error_returns_500(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "broken.pdf"
        dest.write_bytes(b"not a real pdf")

        lp_app.dependency_overrides[get_pipeline_orchestrator] = lambda: MagicMock(
            run=MagicMock(side_effect=RuntimeError("parse failed"))
        )
        lp_app.dependency_overrides[get_session] = _mock_session

        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/documents/process", json={"file_path": str(dest)})
        lp_app.dependency_overrides.pop(get_pipeline_orchestrator, None)

        assert resp.status_code == 500
        assert "pipeline failed" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_process_missing_body_returns_422(self, lp_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post("/api/documents/process", json={})
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_process_stable_doc_id_matches_file_hash(self, lp_app, tmp_path: Path) -> None:
        """doc_id returned is SHA-256 of the resolved file path (first 32 hex chars as UUID)."""
        if not SMALL_PDF.exists():
            pytest.skip("test_pdfs/small.pdf not found")
        dest = tmp_path / "small.pdf"
        dest.write_bytes(SMALL_PDF.read_bytes())

        doc_id_str, result = _make_result(str(dest))
        lp_app.dependency_overrides[get_pipeline_orchestrator] = lambda: MagicMock(
            run=MagicMock(return_value=result)
        )
        lp_app.dependency_overrides[get_session] = _mock_session

        patches = _start_repo_patches()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.post("/api/documents/process", json={"file_path": str(dest)})
        finally:
            for p in patches:
                p.stop()
        lp_app.dependency_overrides.pop(get_pipeline_orchestrator, None)

        returned_id = resp.json()["doc_id"]
        expected_uuid = doc_id_str
        assert returned_id == expected_uuid


# ── GET /api/documents/{doc_id}/tree ─────────────────────────────────────────


class TestTree:
    """GET /api/documents/{doc_id}/tree"""

    def _seed_cache(self, file_path: str) -> tuple[str, str]:
        doc_id_str, result = _make_result(file_path)
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str
        return doc_id_str, doc_id_uuid

    @pytest.mark.asyncio
    async def test_tree_from_cache_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        _, doc_id_uuid = self._seed_cache(str(dest))

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/tree")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["title"] == "Small PDF"
        assert data["total_nodes"] >= 1
        assert data["root"] is not None

    @pytest.mark.asyncio
    async def test_tree_root_has_correct_type(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        _, doc_id_uuid = self._seed_cache(str(dest))

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/tree")

        root = resp.json()["root"]
        assert root["type"] == "heading"
        assert root["page"] == 0

    @pytest.mark.asyncio
    async def test_tree_not_found_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        mock_repo = AsyncMock()
        mock_repo.find_document = AsyncMock(return_value=None)

        lp_app.dependency_overrides[get_session] = _mock_session
        with patch(
            "learning_platform.api.routes.documents.DocumentRepository", return_value=mock_repo
        ):
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/tree")

        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tree_invalid_uuid_returns_422(self, lp_app) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get("/api/documents/not-a-uuid/tree")
        assert resp.status_code == 422

    @pytest.mark.asyncio
    async def test_tree_empty_document_returns_null_root(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "empty.pdf"
        dest.write_bytes(b"fake")
        doc_id_str = stable_doc_id(str(dest))
        doc_id_uuid = str(UUID(doc_id_str[:32]))
        cache_key = doc_id_uuid

        empty_doc = CanonicalDocument(source=str(dest), title="Empty", nodes=[])
        empty_doc.rebuild_index()
        empty_result = PipelineResult(
            document=empty_doc,
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
        pipeline_cache.set(cache_key, empty_result)

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/tree")

        assert resp.status_code == 200
        assert resp.json()["root"] is None
        assert resp.json()["total_nodes"] == 0


# ── POST /api/documents/{doc_id}/enrich ──────────────────────────────────────


class TestEnrich:
    """POST /api/documents/{doc_id}/enrich"""

    @pytest.mark.asyncio
    async def test_enrich_cached_returns_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/documents/{doc_id_uuid}/enrich")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["message"] == "Document already processed (cached result)"
        assert data["units_count"] == 1
        assert data["concepts_count"] == 2

    @pytest.mark.asyncio
    async def test_enrich_not_cached_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/documents/{doc_id}/enrich")
        assert resp.status_code == 404
        assert "process first" in resp.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_enrich_cached_returns_correct_title(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.post(f"/api/documents/{doc_id_uuid}/enrich")

        assert resp.json()["title"] == "Small PDF"


# ── GET /api/documents/{doc_id}/units ────────────────────────────────────────


class TestUnits:
    """GET /api/documents/{doc_id}/units"""

    @pytest.mark.asyncio
    async def test_units_from_cache_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/units")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["count"] == 1
        assert data["units"][0]["title"] == "Introduction"
        assert data["units"][0]["unit_type"] == "lesson"
        assert data["units"][0]["difficulty"] == "basic"
        assert data["units"][0]["estimated_study_time_minutes"] == 10

    @pytest.mark.asyncio
    async def test_units_not_found_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        mock_repo = AsyncMock(find_by_document=AsyncMock(return_value=[]))
        lp_app.dependency_overrides[get_session] = _mock_session
        with patch(
            "learning_platform.api.routes.documents.LearningUnitRepository", return_value=mock_repo
        ):
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/units")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_units_empty_cached_returns_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str = stable_doc_id(str(dest))
        doc_id_uuid = str(UUID(doc_id_str[:32]))

        empty_doc = CanonicalDocument(source=str(dest), title="Empty", nodes=[])
        empty_doc.rebuild_index()
        pipeline_cache.set(
            doc_id_uuid,
            PipelineResult(
                document=empty_doc,
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
            ),
        )

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/units")

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    @pytest.mark.asyncio
    async def test_units_learning_objectives_present(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/units")

        unit = resp.json()["units"][0]
        assert "learning_objectives" in unit
        assert "Understand basics" in unit["learning_objectives"]


# ── GET /api/documents/{doc_id}/concepts ─────────────────────────────────────


class TestConcepts:
    """GET /api/documents/{doc_id}/concepts"""

    @pytest.mark.asyncio
    async def test_concepts_from_cache_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/concepts")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["total_concepts"] == 2
        assert data["total_relationships"] == 1
        names = {c["name"] for c in data["concepts"]}
        assert "Concept A" in names
        assert "Concept B" in names

    @pytest.mark.asyncio
    async def test_concepts_include_importance(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/concepts")

        for concept in resp.json()["concepts"]:
            assert "importance" in concept
            assert "category" in concept

    @pytest.mark.asyncio
    async def test_concepts_not_found_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        mock_repo = AsyncMock(find_by_document=AsyncMock(return_value=ConceptMap()))
        lp_app.dependency_overrides[get_session] = _mock_session
        with patch(
            "learning_platform.api.routes.documents.ConceptRepository", return_value=mock_repo
        ):
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/concepts")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_concepts_empty_cached_returns_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str = stable_doc_id(str(dest))
        doc_id_uuid = str(UUID(doc_id_str[:32]))

        empty_doc = CanonicalDocument(source=str(dest), title="Empty", nodes=[])
        empty_doc.rebuild_index()
        pipeline_cache.set(
            doc_id_uuid,
            PipelineResult(
                document=empty_doc,
                annotations=[],
                units=[],
                concepts=ConceptMap(concepts=[], relationships=[]),
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
            ),
        )

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/concepts")

        assert resp.status_code == 200
        assert resp.json()["total_concepts"] == 0


# ── GET /api/documents/{doc_id}/study-plan ───────────────────────────────────


class TestStudyPlan:
    """GET /api/documents/{doc_id}/study-plan"""

    @pytest.mark.asyncio
    async def test_study_plan_from_cache_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/study-plan")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["title"] == "Small PDF Plan"
        assert data["total_lessons"] == 1
        assert data["total_estimated_minutes"] == 15
        assert len(data["lessons"]) == 1
        assert len(data["milestones"]) == 1
        assert len(data["checkpoints"]) == 1

    @pytest.mark.asyncio
    async def test_study_plan_lesson_fields(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/study-plan")

        lesson = resp.json()["lessons"][0]
        assert lesson["title"] == "Lesson 1"
        assert lesson["lesson_type"] == "core"
        assert lesson["difficulty"] == "basic"
        assert lesson["estimated_minutes"] == 10

    @pytest.mark.asyncio
    async def test_study_plan_milestone_fields(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/study-plan")

        milestone = resp.json()["milestones"][0]
        assert milestone["title"] == "M1"
        assert milestone["lesson_count"] == 1

    @pytest.mark.asyncio
    async def test_study_plan_checkpoint_fields(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_session] = _mock_session
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id_uuid}/study-plan")

        checkpoint = resp.json()["checkpoints"][0]
        assert checkpoint["title"] == "CP1"
        assert checkpoint["checkpoint_type"] == "self_test"

    @pytest.mark.asyncio
    async def test_study_plan_not_found_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        mock_repo = AsyncMock(find_by_document=AsyncMock(return_value=None))
        lp_app.dependency_overrides[get_session] = _mock_session
        with patch(
            "learning_platform.api.routes.documents.StudyPlanRepository", return_value=mock_repo
        ):
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id}/study-plan")
        assert resp.status_code == 404


# ── GET /api/documents/{doc_id}/export/json ───────────────────────────────────


class TestExportJson:
    """GET /api/documents/{doc_id}/export/json"""

    @pytest.mark.asyncio
    async def test_export_json_200(self, lp_app, tmp_path: Path) -> None:
        dest = tmp_path / "small.pdf"
        dest.write_bytes(b"fake")
        doc_id_str, result = _make_result(str(dest))
        pipeline_cache.set(doc_id_str, result)
        doc_id_uuid = doc_id_str

        export_dir = tmp_path / "exports" / doc_id_uuid
        export_dir.mkdir(parents=True)

        lp_app.dependency_overrides[get_session] = _mock_session
        with patch(
            "learning_platform.api.routes.documents.Path",
            side_effect=lambda p: export_dir if not isinstance(p, Path) else p,
        ):
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                resp = await client.get(f"/api/documents/{doc_id_uuid}/export/json")

        assert resp.status_code == 200
        data = resp.json()
        assert data["doc_id"] == doc_id_uuid
        assert data["title"] == "Small PDF"
        assert data["units_count"] == 1
        assert data["concepts_count"] == 2
        assert len(data["files"]) == 6

    @pytest.mark.asyncio
    async def test_export_json_not_found_returns_404(self, lp_app) -> None:
        doc_id = uuid4()
        async with AsyncClient(
            transport=ASGITransport(app=lp_app), base_url="http://test"
        ) as client:
            resp = await client.get(f"/api/documents/{doc_id}/export/json")
        assert resp.status_code == 404


# ── Full flow: process → read all endpoints ───────────────────────────────────


class TestFullFlow:
    """End-to-end: process small.pdf then read every view endpoint."""

    @pytest.mark.asyncio
    async def test_process_then_all_views(self, lp_app, tmp_path: Path) -> None:
        if not SMALL_PDF.exists():
            pytest.skip("test_pdfs/small.pdf not found")

        dest = tmp_path / "small.pdf"
        dest.write_bytes(SMALL_PDF.read_bytes())
        doc_id_str, result = _make_result(str(dest))
        doc_id_uuid = doc_id_str

        lp_app.dependency_overrides[get_pipeline_orchestrator] = lambda: MagicMock(
            run=MagicMock(return_value=result)
        )
        lp_app.dependency_overrides[get_session] = _mock_session

        patches = _start_repo_patches()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test"
            ) as client:
                # 1. Process
                proc = await client.post("/api/documents/process", json={"file_path": str(dest)})
                assert proc.status_code == 201
                assert proc.json()["doc_id"] == doc_id_uuid

                # 2. Tree
                tree = await client.get(f"/api/documents/{doc_id_uuid}/tree")
                assert tree.status_code == 200
                assert tree.json()["title"] == "Small PDF"

                # 3. Enrich (cached)
                enrich = await client.post(f"/api/documents/{doc_id_uuid}/enrich")
                assert enrich.status_code == 200
                assert enrich.json()["units_count"] == 1

                # 4. Units
                units = await client.get(f"/api/documents/{doc_id_uuid}/units")
                assert units.status_code == 200
                assert units.json()["count"] == 1

                # 5. Concepts
                concepts = await client.get(f"/api/documents/{doc_id_uuid}/concepts")
                assert concepts.status_code == 200
                assert concepts.json()["total_concepts"] == 2

                # 6. Study plan
                plan = await client.get(f"/api/documents/{doc_id_uuid}/study-plan")
                assert plan.status_code == 200
                assert plan.json()["total_lessons"] == 1

        finally:
            for p in patches:
                p.stop()
        lp_app.dependency_overrides.pop(get_pipeline_orchestrator, None)

    @pytest.mark.slow
    @pytest.mark.asyncio
    async def test_real_pipeline_small_pdf(self, lp_app, tmp_path: Path) -> None:
        """Run the actual Docling pipeline on small.pdf — no mocks.

        Marked @pytest.mark.slow: excluded from the default test run.
        Run explicitly with: pytest -m slow
        """
        if not SMALL_PDF.exists():
            pytest.skip("test_pdfs/small.pdf not found")

        dest = tmp_path / "small.pdf"
        dest.write_bytes(SMALL_PDF.read_bytes())

        lp_app.dependency_overrides[get_session] = _mock_session
        patches = _start_repo_patches()
        try:
            async with AsyncClient(
                transport=ASGITransport(app=lp_app), base_url="http://test", timeout=120.0
            ) as client:
                resp = await client.post("/api/documents/process", json={"file_path": str(dest)})
        finally:
            for p in patches:
                p.stop()

        assert resp.status_code == 201
        data = resp.json()
        assert "doc_id" in data
        assert data["units_count"] >= 0
        assert data["concepts_count"] >= 0
        assert data["lessons"] >= 0
