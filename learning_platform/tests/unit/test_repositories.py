"""Tests for repositories using SQLite in-memory async database."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from learning_platform.infrastructure.persistence.models.base import Base
from learning_platform.infrastructure.persistence.repositories.annotation import (
    AnnotationRepository,
)
from learning_platform.infrastructure.persistence.repositories.concept import ConceptRepository
from learning_platform.infrastructure.persistence.repositories.document import DocumentRepository
from learning_platform.infrastructure.persistence.repositories.knowledge_graph import (
    KnowledgeGraphRepository,
)
from learning_platform.infrastructure.persistence.repositories.learning_unit import (
    LearningUnitRepository,
)
from learning_platform.infrastructure.persistence.repositories.sequence import StudyPlanRepository
from learning_platform.models.annotation import DefinitionAnnotation
from learning_platform.models.concept import (
    Concept,
    ConceptCategory,
    ConceptMap,
    ConceptRelationship,
    RelationType,
)
from learning_platform.models.document import (
    CanonicalDocument,
    DocumentMetadata,
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
    Milestone,
    StudyPlan,
)

# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
async def engine():
    eng = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with eng.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield eng
    await eng.dispose()


@pytest.fixture
async def session(engine):
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as sess:
        yield sess


def _make_doc_id() -> uuid.UUID:
    return uuid.uuid4()


def _make_document(doc_id: uuid.UUID) -> CanonicalDocument:
    root = DocumentNode(
        id=doc_id,
        content=Heading(level=HeadingLevel.CHAPTER, text=StyledText(runs=[TextRun(text="Doc")])),
    )
    return CanonicalDocument(
        source="test.pdf",
        title="Test",
        metadata=DocumentMetadata(title="Test", author="A"),
        nodes=[root],
    )


def _make_unit(doc_id: uuid.UUID, **overrides: object) -> LearningUnit:
    defaults = {
        "unit_type": UnitType.LESSON,
        "title": "Unit 1",
        "difficulty": Difficulty.BASIC,
        "parent_id": None,
        "children_ids": [],
        "prerequisite_ids": [],
        "source_node_ids": [],
        "content_references": [],
        "definitions": [],
        "examples": [],
        "figures": [],
        "tables": [],
        "equations": [],
        "exercises": [],
        "learning_objectives": [],
        "metadata": {},
    }
    defaults.update(overrides)
    return LearningUnit(**defaults)  # type: ignore[arg-type]


def _make_annotation(doc_id: uuid.UUID) -> DefinitionAnnotation:
    return DefinitionAnnotation(
        node_id=uuid.uuid4(),
        term="foo",
        definition_text="bar",
        detector="test",
    )


def _make_concept_map() -> ConceptMap:
    c1 = Concept(name="A", category=ConceptCategory.CONCEPT, importance=0.9)
    c2 = Concept(name="B", category=ConceptCategory.SKILL, importance=0.5)
    rel = ConceptRelationship(
        source_id=c1.id, target_id=c2.id, relation_type=RelationType.PREREQUISITE
    )
    return ConceptMap(concepts=[c1, c2], relationships=[rel])


def _make_graph() -> KnowledgeGraph:
    n1 = GraphNode(node_type=NodeType.UNIT, label="U1")
    n2 = GraphNode(node_type=NodeType.CONCEPT, label="C1")
    e = GraphEdge(source_id=n1.id, target_id=n2.id, edge_type=EdgeType.REFERENCES)
    return KnowledgeGraph(nodes=[n1, n2], edges=[e])


def _make_plan() -> StudyPlan:
    m = Milestone(order=0, title="M1", lesson_ids=[])
    lesson = Lesson(unit_id=uuid.uuid4(), order=0, title="L1", milestone_id=m.id)
    m.lesson_ids = [lesson.id]
    cp = Checkpoint(
        milestone_id=m.id,
        order=0,
        title="CP1",
        checkpoint_type=CheckpointType.QUIZ,
    )
    return StudyPlan(
        title="Plan",
        lessons=[lesson],
        milestones=[m],
        checkpoints=[cp],
        total_lessons=1,
    )


# ── DocumentRepository ───────────────────────────────────────────────────────


class TestDocumentRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        doc = _make_document(doc_id)
        repo = DocumentRepository(session)

        await repo.save_document(doc)
        loaded = await repo.find_document(doc_id)

        assert loaded is not None
        assert loaded.source == "test.pdf"
        assert loaded.title == "Test"

    async def test_find_nonexistent(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        assert await repo.find_document(uuid.uuid4()) is None

    async def test_delete(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        doc = _make_document(doc_id)
        repo = DocumentRepository(session)
        await repo.save_document(doc)

        assert await repo.delete_by_id(doc_id) is True
        assert await repo.find_document(doc_id) is None

    async def test_delete_nonexistent(self, session: AsyncSession) -> None:
        repo = DocumentRepository(session)
        assert await repo.delete_by_id(uuid.uuid4()) is False


# ── LearningUnitRepository ───────────────────────────────────────────────────


class TestLearningUnitRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        unit = _make_unit(doc_id, title="Hello Unit")
        repo = LearningUnitRepository(session)

        await repo.save_unit(unit, doc_id)
        units = await repo.find_by_document(doc_id)

        assert len(units) == 1
        assert units[0].title == "Hello Unit"

    async def test_find_by_type(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        u1 = _make_unit(doc_id, unit_type=UnitType.LESSON, title="L1")
        u2 = _make_unit(doc_id, unit_type=UnitType.TOPIC, title="T1")
        repo = LearningUnitRepository(session)
        await repo.save_all_units([u1, u2], doc_id)

        lessons = await repo.find_by_type(doc_id, UnitType.LESSON)
        assert len(lessons) == 1
        assert lessons[0].title == "L1"

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = LearningUnitRepository(session)
        await repo.save_all_units([_make_unit(doc_id), _make_unit(doc_id)], doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count == 2
        assert await repo.find_by_document(doc_id) == []


# ── AnnotationRepository ─────────────────────────────────────────────────────


class TestAnnotationRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        ann = _make_annotation(doc_id)
        repo = AnnotationRepository(session)

        await repo.save_annotation(ann, doc_id)
        found = await repo.find_by_document(doc_id)

        assert len(found) == 1
        assert found[0].type == "definition"

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = AnnotationRepository(session)
        await repo.save_annotation(_make_annotation(doc_id), doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count == 1


# ── ConceptRepository ────────────────────────────────────────────────────────


class TestConceptRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        cmap = _make_concept_map()
        repo = ConceptRepository(session)

        await repo.save_concept_map(cmap, doc_id)
        loaded = await repo.find_by_document(doc_id)

        assert len(loaded.concepts) == 2
        assert len(loaded.relationships) == 1

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = ConceptRepository(session)
        await repo.save_concept_map(_make_concept_map(), doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count >= 2


# ── KnowledgeGraphRepository ─────────────────────────────────────────────────


class TestKnowledgeGraphRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        graph = _make_graph()
        repo = KnowledgeGraphRepository(session)

        await repo.save_graph(graph, doc_id)
        loaded = await repo.find_by_document(doc_id)

        assert loaded is not None
        assert len(loaded.nodes) == 2
        assert len(loaded.edges) == 1

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = KnowledgeGraphRepository(session)
        await repo.save_graph(_make_graph(), doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count == 1
        assert await repo.find_by_document(doc_id) is None


# ── StudyPlanRepository ──────────────────────────────────────────────────────


class TestStudyPlanRepository:
    async def test_save_and_find(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        plan = _make_plan()
        repo = StudyPlanRepository(session)

        await repo.save_plan(plan, doc_id)
        loaded = await repo.find_by_document(doc_id)

        assert loaded is not None
        assert loaded.title == "Plan"
        assert len(loaded.lessons) == 1
        assert len(loaded.milestones) == 1
        assert len(loaded.checkpoints) == 1

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = StudyPlanRepository(session)
        await repo.save_plan(_make_plan(), doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count == 1
        assert await repo.find_by_document(doc_id) is None
