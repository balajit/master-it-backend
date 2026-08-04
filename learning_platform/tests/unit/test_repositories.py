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
    from learning_platform.infrastructure.persistence.models.reviewer_run import (
        ReviewerPageResultRow,
        ReviewerRunRow,
    )

    _ = (ReviewerRunRow, ReviewerPageResultRow)
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

    async def test_save_existing_doc_id_updates_row(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = DocumentRepository(session)

        original = _make_document(doc_id)
        original.source = "original.pdf"
        original.title = "Original"
        await repo.save_document(original, doc_id=doc_id)

        updated = _make_document(doc_id)
        updated.source = "updated.pdf"
        updated.title = "Updated"
        await repo.save_document(updated, doc_id=doc_id)

        loaded = await repo.find_document(doc_id)
        assert loaded is not None
        assert loaded.source == "updated.pdf"
        assert loaded.title == "Updated"


class TestDocumentProcessRepository:
    async def test_delete_entries_by_ids_removes_process_rows_and_pipeline_logs(
        self, session: AsyncSession
    ) -> None:
        from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row_1 = await repo.create_entry("source-1.pdf", "/tmp/source-1.pdf")
        row_2 = await repo.create_entry("source-2.pdf", "/tmp/source-2.pdf")

        await session.execute(
            PipelineLogRow.__table__.insert(),
            [
                {
                    "source": row_1.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_1.id,
                },
                {
                    "source": row_1.source,
                    "stage": "normalizer",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_1.id,
                },
                {
                    "source": row_2.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_2.id,
                },
            ],
        )
        await session.flush()

        deleted_ids, not_found_ids, deleted_log_count = await repo.delete_entries_by_ids(
            [row_2.id, row_1.id, row_2.id, 999999]
        )

        assert deleted_ids == [row_1.id, row_2.id]
        assert not_found_ids == [999999]
        assert deleted_log_count == 3
        assert await repo.find_by_id(row_1.id) is None
        assert await repo.find_by_id(row_2.id) is None

    async def test_delete_entries_by_ids_with_empty_input(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        deleted_ids, not_found_ids, deleted_log_count = await repo.delete_entries_by_ids([])

        assert deleted_ids == []
        assert not_found_ids == []
        assert deleted_log_count == 0

    async def test_create_retry_entry_copies_resume_state(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        base = await repo.create_entry("source.pdf", "/tmp/source.pdf")
        await repo.mark_completed(base)
        base.status = "failed"
        await repo.record_stage_completed(base, "concept_extractor")
        await repo.update_resume_state(base, resume_state={"normalized_document": {"source": "x"}})
        await repo.record_stage_failed(base, "graph_builder", "boom")

        retry = await repo.create_retry_entry(base)

        assert retry.run_mode == "retry"
        assert retry.retry_count == base.retry_count
        assert retry.last_completed_stage == "concept_extractor"
        assert retry.failed_stage == "graph_builder"
        assert retry.resume_state_json == {"normalized_document": {"source": "x"}}

    async def test_resolve_resume_from_row_retry_graph_stage(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row = await repo.create_entry("source.pdf", "/tmp/source.pdf", run_mode="retry")
        row.last_completed_stage = "concept_extractor"
        row.resume_state_json = {"units": []}

        stage, payload = repo.resolve_resume_from_row(row)
        assert stage == "graph_builder"
        assert payload == {"units": []}

    async def test_resolve_resume_from_row_reprocess_forces_parser(
        self, session: AsyncSession
    ) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row = await repo.create_entry("source.pdf", "/tmp/source.pdf", run_mode="reprocess")
        row.last_completed_stage = "graph_builder"
        row.resume_state_json = {"units": ["stale"]}

        stage, payload = repo.resolve_resume_from_row(row)
        assert stage == "parser"
        assert payload == {}

    async def test_requeue_processing_after_restart_marks_retry(
        self, session: AsyncSession
    ) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row = await repo.create_entry("source.pdf", "/tmp/source.pdf")
        await repo.mark_processing(row)
        await repo.requeue_processing_after_restart(row, "Recovered")

        assert row.status == "pending"
        assert row.run_mode == "retry"
        assert row.error_message == "Recovered"

    async def test_mark_book_pending_sets_processing(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row = await repo.create_entry("source.pdf", "/tmp/source.pdf")
        await repo.mark_book_pending(row, "BookPipeline error, will retry")

        assert row.status == "processing"
        assert row.error_message == "BookPipeline error, will retry"

    async def test_list_entries_and_pipeline_logs_by_ids(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.models.pipeline_log import PipelineLogRow
        from learning_platform.infrastructure.persistence.repositories.document_process import (
            DocumentProcessRepository,
        )

        repo = DocumentProcessRepository(session)
        row_1 = await repo.create_entry("source-1.pdf", "/tmp/source-1.pdf")
        row_2 = await repo.create_entry("source-2.pdf", "/tmp/source-2.pdf")
        await session.execute(
            PipelineLogRow.__table__.insert(),
            [
                {
                    "source": row_1.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_1.id,
                },
                {
                    "source": row_2.source,
                    "stage": "parser",
                    "output": "ok",
                    "result": "success",
                    "document_process_id": row_2.id,
                },
            ],
        )
        await session.flush()

        entries = await repo.list_entries_by_ids([row_2.id, 999999, row_1.id, row_2.id])
        logs = await repo.list_pipeline_logs_by_process_ids([row_2.id, row_1.id, row_2.id])

        assert [entry.id for entry in entries] == [row_1.id, row_2.id]
        assert [log.document_process_id for log in logs] == [row_1.id, row_2.id]


class TestReviewerRunRepositories:
    async def test_reviewer_run_and_page_result_lifecycle(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document import (
            DocumentRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.reviewer_run import (
            ReviewerPageResultRepository,
            ReviewerRunRepository,
        )

        doc_id = _make_doc_id()
        doc_repo = DocumentRepository(session)
        await doc_repo.save_document(_make_document(doc_id), doc_id=doc_id)

        run_repo = ReviewerRunRepository(session)
        page_repo = ReviewerPageResultRepository(session)

        run_row = await run_repo.create_processing_run(
            requested_lp_documents_id=doc_id,
            resolved_lp_documents_id=doc_id,
            resolved_document_name="test.pdf",
            metadata={"reviewed_page_numbers": [1]},
        )

        await page_repo.create_page_result(
            reviewer_run_id=run_row.id,
            lp_documents_id=doc_id,
            page_number=1,
            review_status="reviewed",
            review_error=None,
            extracted_text_char_count=123,
            summary="Looks good",
            strengths=["clear"],
            issues=[],
            recommendations=["none"],
            verdict="approved",
            confidence=0.93,
            metadata={"deterministic_verifier": {"text_similarity_ratio": 1.0}},
        )

        page_rows = await page_repo.list_by_run_id(run_row.id)
        assert len(page_rows) == 1
        assert page_rows[0].review_status == "reviewed"

        await run_repo.mark_completed(
            run_row,
            aggregate_verdict="approved",
            aggregate_summary="Reviewed 1 page(s)",
            metadata={"reviewed_pages_count": 1},
        )

        loaded_run = await run_repo.find_by_id(run_row.id)
        assert loaded_run is not None
        assert loaded_run.status == "completed"
        assert loaded_run.aggregate_verdict == "approved"

    async def test_reviewer_run_mark_failed(self, session: AsyncSession) -> None:
        from learning_platform.infrastructure.persistence.repositories.document import (
            DocumentRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.reviewer_run import (
            ReviewerRunRepository,
        )

        doc_id = _make_doc_id()
        doc_repo = DocumentRepository(session)
        await doc_repo.save_document(_make_document(doc_id), doc_id=doc_id)

        run_repo = ReviewerRunRepository(session)
        run_row = await run_repo.create_processing_run(
            requested_lp_documents_id=doc_id,
            resolved_lp_documents_id=doc_id,
            resolved_document_name="failed.pdf",
            metadata={"reviewed_page_numbers": [1, 2]},
        )

        await run_repo.mark_failed(
            run_row,
            error_message="deterministic failure",
            metadata={"processed_pages_count": 1},
        )

        loaded_run = await run_repo.find_by_id(run_row.id)
        assert loaded_run is not None
        assert loaded_run.status == "failed"
        assert loaded_run.error_message == "deterministic failure"


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
        assert loaded.id == plan.id
        assert loaded.title == "Plan"
        assert len(loaded.lessons) == 1
        assert len(loaded.milestones) == 1
        assert len(loaded.checkpoints) == 1

    async def test_save_plan_uses_plan_id_not_zero_fallback(self, session: AsyncSession) -> None:
        first_doc_id = _make_doc_id()
        second_doc_id = _make_doc_id()
        repo = StudyPlanRepository(session)

        first_plan = StudyPlan(title="First")
        second_plan = StudyPlan(title="Second")

        await repo.save_plan(first_plan, first_doc_id)
        await repo.save_plan(second_plan, second_doc_id)

        loaded_first = await repo.find_by_document(first_doc_id)
        loaded_second = await repo.find_by_document(second_doc_id)

        assert loaded_first is not None
        assert loaded_second is not None
        assert loaded_first.id == first_plan.id
        assert loaded_second.id == second_plan.id
        assert loaded_first.id != loaded_second.id

    async def test_delete_by_document(self, session: AsyncSession) -> None:
        doc_id = _make_doc_id()
        repo = StudyPlanRepository(session)
        await repo.save_plan(_make_plan(), doc_id)
        count = await repo.delete_by_document(doc_id)
        assert count == 1
        assert await repo.find_by_document(doc_id) is None
