"""Test driver for the Learning Platform API.

This is a test-friendly version of driver.py that uses the FastAPI test client
instead of requiring a live server. It tests all the document pipeline routes
with the actual test PDF.
"""

from __future__ import annotations

import json
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
        database_url="sqlite+aiosqlite:///:memory:",
        debug=True,
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


async def _mock_get_current_user() -> dict[str, Any]:
    """Mock get_current_user dependency."""
    return {"id": 1, "email": "test@example.com"}


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
# Driver Test
# ══════════════════════════════════════════════════════════════════════════════


class TestDriverWithRealPDF:
    """Test the driver workflow with real PDF."""

    @pytest.mark.asyncio
    async def test_driver_full_workflow(self, app, _clear_cache: None, tmp_path: Path) -> None:
        """Test the complete driver workflow with real PDF."""
        if not TEST_PDF_PATH.exists():
            pytest.skip(f"Test PDF not found: {TEST_PDF_PATH}")

        # Step 1: Upload
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
        print(f"[OK] Document uploaded: {doc_id}")

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
                    process_resp = await client.post(f"/api/documents/{doc_id}/process")
            finally:
                for p in repo_patches:
                    p.stop()

        assert process_resp.status_code == 200
        process_data = process_resp.json()
        print(f"[OK] Pipeline completed: {json.dumps(process_data, indent=2)}")

        # Step 3: View Tree
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            tree_resp = await client.get(f"/api/documents/{doc_id}/tree")
        assert tree_resp.status_code == 200
        tree_data = tree_resp.json()
        print(f"[OK] Document tree: {tree_data.get('total_nodes', 0)} nodes")

        # Step 4: View Units
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            units_resp = await client.get(f"/api/documents/{doc_id}/units")
        assert units_resp.status_code == 200
        units_data = units_resp.json()
        print(f"[OK] Learning units: {units_data.get('count', 0)} units")

        # Step 5: View Concepts
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            concepts_resp = await client.get(f"/api/documents/{doc_id}/concepts")
        assert concepts_resp.status_code == 200
        concepts_data = concepts_resp.json()
        print(
            f"[OK] Concepts: {concepts_data.get('total_concepts', 0)} concepts, "
            f"{concepts_data.get('total_relationships', 0)} relationships"
        )

        # Step 6: View Study Plan
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            plan_resp = await client.get(f"/api/documents/{doc_id}/study-plan")
        assert plan_resp.status_code == 200
        plan_data = plan_resp.json()
        print(f"[OK] Study plan: {plan_data.get('total_lessons', 0)} lessons")

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
        export_data = export_resp.json()
        print(f"[OK] JSON export: {export_data.get('title', 'Unknown')}")

        # Verify all results
        assert process_data["doc_id"] == str(doc_id)
        assert process_data["title"] == "Test Document"
        assert process_data["units_count"] == 1
        assert process_data["concepts_count"] == 2
        assert process_data["graph_nodes"] == 2
        assert process_data["graph_edges"] == 1
        assert process_data["lessons"] == 1
        assert process_data["milestones"] == 1

        assert tree_data["doc_id"] == str(doc_id)
        assert tree_data["title"] == "Test Document"
        assert tree_data["total_nodes"] >= 1

        assert units_data["doc_id"] == str(doc_id)
        assert units_data["count"] == 1
        assert units_data["units"][0]["title"] == "Test Lesson"

        assert concepts_data["doc_id"] == str(doc_id)
        assert concepts_data["total_concepts"] == 2
        assert concepts_data["total_relationships"] == 1

        assert plan_data["doc_id"] == str(doc_id)
        assert plan_data["title"] == "Test Study Plan"
        assert plan_data["total_lessons"] == 1
        assert plan_data["total_estimated_minutes"] == 25

        assert export_data["doc_id"] == str(doc_id)
        assert export_data["title"] == "Test Document"
        assert export_data["units_count"] == 1
        assert export_data["concepts_count"] == 2

        print("\n[OK] All driver workflow steps completed successfully!")
