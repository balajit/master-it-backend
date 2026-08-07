"""Unit tests for the Agent Pipeline (Pipeline 3).

Tests cover:
- AgentPipeline.run() — happy path with mocked CuratorAgent and BookRepository
- AgentPipeline.run() — raises ValueError when no book found
- CuratorAgent.run_pipeline() — delegates to sub-agents, lesson progress tracking
- CuratorAgent backward-compat analyze() interface
- Individual sub-agent JSON parsing and output validation
- AgentPipelineOutputRepository bulk-insert helpers
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import UUID, uuid4

import pytest

from learning_platform.models.agent_pipeline import (
    AgentFlashcard,
    AgentPipelineResult,
    KeywordItem,
    PracticeQuestion,
    QuizQuestion,
    SummaryItem,
)
from learning_platform.models.book import (
    BookChapter,
    BookLesson,
    BookPage,
    CanonicalBook,
    TextItem,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _make_book(num_lessons: int = 2) -> CanonicalBook:
    doc_id = uuid4()
    lessons = [
        BookLesson(
            id=uuid4(),
            title=f"Lesson {i}",
            order=i,
            pages=[
                BookPage(
                    id=uuid4(),
                    page_number=i,
                    items=[TextItem(content=f"Content for lesson {i}.")],
                )
            ],
        )
        for i in range(num_lessons)
    ]
    chapter = BookChapter(id=uuid4(), title="Chapter 1", order=0, lessons=lessons)
    return CanonicalBook(id=uuid4(), document_id=doc_id, chapters=[chapter])


def _make_session_mock() -> MagicMock:
    """Return a session mock that satisfies repository calls."""
    session = MagicMock()
    execute_result = MagicMock()
    execute_result.scalars.return_value.first.return_value = None
    session.execute = AsyncMock(return_value=execute_result)
    session.flush = AsyncMock()
    session.add = MagicMock()
    session.add_all = MagicMock()
    return session


# ── AgentPipeline ─────────────────────────────────────────────────────────────


class TestAgentPipeline:
    @pytest.mark.asyncio
    async def test_run_raises_if_book_not_found(self) -> None:
        from learning_platform.pipeline.agent_pipeline import AgentPipeline

        session = MagicMock()
        pipeline = AgentPipeline(session)
        pipeline._book_repo = MagicMock()
        pipeline._book_repo.find_by_document = AsyncMock(return_value=None)

        with pytest.raises(ValueError, match="No CanonicalBook found"):
            await pipeline.run(uuid4(), agent_process_id=1)

    @pytest.mark.asyncio
    async def test_run_happy_path_calls_curator(self) -> None:
        from learning_platform.pipeline.agent_pipeline import AgentPipeline

        doc_id = uuid4()
        book = _make_book(num_lessons=1)
        book = book.model_copy(update={"document_id": doc_id})

        session = MagicMock()
        pipeline = AgentPipeline(session)
        pipeline._book_repo = MagicMock()
        pipeline._book_repo.find_by_document = AsyncMock(return_value=book)

        lesson_id = book.chapters[0].lessons[0].id
        fake_result = AgentPipelineResult(
            document_id=doc_id,
            keywords=[KeywordItem(lesson_id=lesson_id, term="T", definition="D")],
        )
        pipeline._curator = MagicMock()
        pipeline._curator.run_pipeline = AsyncMock(return_value=fake_result)

        result = await pipeline.run(doc_id, agent_process_id=42)

        assert result.document_id == doc_id
        assert len(result.keywords) == 1
        # Curator called with book, document_id, agent_process_id, session
        pipeline._curator.run_pipeline.assert_awaited_once_with(
            book=book,
            document_id=doc_id,
            agent_process_id=42,
            session=session,
        )


# ── CuratorAgent orchestrator ─────────────────────────────────────────────────


class TestCuratorAgentOrchestrator:
    @pytest.mark.asyncio
    async def test_run_pipeline_collects_sub_agent_output(self) -> None:
        from learning_platform.agents.curator.orchestrator import CuratorAgent
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        book = _make_book(num_lessons=1)
        lesson_id = book.chapters[0].lessons[0].id
        doc_id = book.document_id

        agent = CuratorAgent()
        session = _make_session_mock()

        kw = [KeywordItem(lesson_id=lesson_id, term="X", definition="Def")]
        sm = [SummaryItem(lesson_id=lesson_id, content="Sum")]
        fl = [AgentFlashcard(lesson_id=lesson_id, front="F", back="B")]
        qz = [
            QuizQuestion(
                lesson_id=lesson_id, question="Q?", choices=["a", "b", "c", "d"], correct_index=0
            )
        ]
        pr = [
            PracticeQuestion(
                lesson_id=lesson_id, question="P?", choices=["a", "b", "c", "d"], correct_index=1
            )
        ]

        agent._keywords_agent.run = AsyncMock(return_value=kw)
        agent._summaries_agent.run = AsyncMock(return_value=sm)
        agent._flashcards_agent.run = AsyncMock(return_value=fl)
        agent._quizzes_agent.run = AsyncMock(return_value=qz)
        agent._practice_agent.run = AsyncMock(return_value=pr)

        # Mock progress repo to return no existing progress (first run)
        progress_row = MagicMock()
        progress_row.status = "pending"

        # Mock completion repo to return all 5 agents completed after run
        with (
            patch.object(
                AgentLessonProgressRepository,
                "find",
                new=AsyncMock(return_value=None),
            ),
            patch.object(
                AgentLessonProgressRepository,
                "create",
                new=AsyncMock(return_value=progress_row),
            ),
            patch.object(
                AgentLessonProgressRepository,
                "mark_completed",
                new=AsyncMock(),
            ),
            patch.object(
                AgentLessonCompletionRepository,
                "find_completed_agents",
                new=AsyncMock(
                    return_value={"keywords", "summaries", "flashcards", "quizzes", "practice"}
                ),
            ),
        ):
            result = await agent.run_pipeline(
                book=book,
                document_id=doc_id,
                agent_process_id=1,
                session=session,
            )

        assert result.document_id == doc_id
        assert result.keywords == kw
        assert result.summaries == sm
        assert result.flashcards == fl
        assert result.quiz_questions == qz
        assert result.practice_questions == pr

    @pytest.mark.asyncio
    async def test_run_pipeline_marks_lesson_failed_on_sub_agent_error(self) -> None:
        """When a sub-agent raises, the lesson is marked failed and pipeline raises partial failure."""
        from learning_platform.agents.curator.orchestrator import CuratorAgent
        from learning_platform.pipeline.agent_pipeline import AgentPipelinePartialFailureError
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_progress import (
            AgentLessonProgressRepository,
        )
        from learning_platform.infrastructure.persistence.repositories.agent_lesson_completions import (
            AgentLessonCompletionRepository,
        )

        book = _make_book(num_lessons=1)
        agent = CuratorAgent()
        session = _make_session_mock()

        agent._keywords_agent.run = AsyncMock(side_effect=RuntimeError("LLM down"))
        agent._summaries_agent.run = AsyncMock(return_value=[])
        agent._flashcards_agent.run = AsyncMock(return_value=[])
        agent._quizzes_agent.run = AsyncMock(return_value=[])
        agent._practice_agent.run = AsyncMock(return_value=[])

        progress_row = MagicMock()
        progress_row.status = "pending"
        mark_failed_mock = AsyncMock()

        with (
            patch.object(AgentLessonProgressRepository, "find", new=AsyncMock(return_value=None)),
            patch.object(
                AgentLessonProgressRepository, "create", new=AsyncMock(return_value=progress_row)
            ),
            patch.object(AgentLessonProgressRepository, "mark_failed", new=mark_failed_mock),
            patch.object(
                AgentLessonCompletionRepository,
                "find_completed_agents",
                new=AsyncMock(return_value=set()),
            ),
        ):
            with pytest.raises(AgentPipelinePartialFailureError):
                await agent.run_pipeline(
                    book=book,
                    document_id=book.document_id,
                    agent_process_id=1,
                    session=session,
                )

        mark_failed_mock.assert_awaited_once()

    def test_analyze_backward_compat_interface_exists(self) -> None:
        from learning_platform.agents.curator.orchestrator import CuratorAgent

        agent = CuratorAgent()
        assert callable(agent.analyze)
        assert callable(agent.aanalyze)


# ── QuizzesAgent output validation ───────────────────────────────────────────


class TestQuizzesAgent:
    def test_valid_mcq_parsed_correctly(self) -> None:
        from learning_platform.agents.curator.sub_agents.quizzes import _validate_question

        lesson_id = uuid4()
        entry = {
            "question": "What is an atom?",
            "choices": ["A fruit", "Smallest unit", "A planet", "A wave"],
            "correct_index": 1,
            "explanation": "Atoms are the smallest units of matter.",
        }
        q = _validate_question(entry, lesson_id)

        assert q is not None
        assert q.question == "What is an atom?"
        assert len(q.choices) == 4
        assert q.correct_index == 1
        assert q.explanation == "Atoms are the smallest units of matter."

    def test_invalid_correct_index_clamped_to_zero(self) -> None:
        from learning_platform.agents.curator.sub_agents.quizzes import _validate_question

        entry = {
            "question": "Q?",
            "choices": ["A", "B", "C", "D"],
            "correct_index": 99,
        }
        q = _validate_question(entry, uuid4())
        assert q is not None
        assert q.correct_index == 0

    def test_missing_question_returns_none(self) -> None:
        from learning_platform.agents.curator.sub_agents.quizzes import _validate_question

        entry = {"choices": ["A", "B"], "correct_index": 0}
        result = _validate_question(entry, uuid4())
        assert result is None

    def test_too_few_choices_returns_none(self) -> None:
        from learning_platform.agents.curator.sub_agents.quizzes import _validate_question

        entry = {"question": "Q?", "choices": ["Only one"], "correct_index": 0}
        result = _validate_question(entry, uuid4())
        assert result is None


# ── AgentPipelineOutputRepository ────────────────────────────────────────────


class TestAgentPipelineOutputRepository:
    @pytest.mark.asyncio
    async def test_save_keywords_calls_add_all(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )

        session = MagicMock()
        session.flush = AsyncMock()
        repo = AgentPipelineOutputRepository(session)

        lesson_id = uuid4()
        items = [KeywordItem(lesson_id=lesson_id, term="T", definition="D")]
        await repo.save_keywords("doc-1", items)

        session.add_all.assert_called_once()
        session.flush.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_save_empty_list_is_noop(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )

        session = MagicMock()
        repo = AgentPipelineOutputRepository(session)
        await repo.save_keywords("doc-1", [])
        session.add_all.assert_not_called()

    @pytest.mark.asyncio
    async def test_save_quiz_questions_serialises_choices_as_json(self) -> None:
        from learning_platform.infrastructure.persistence.repositories.agent_pipeline_outputs import (
            AgentPipelineOutputRepository,
        )
        from learning_platform.infrastructure.persistence.models.agent_pipeline_outputs import (
            QuizQuestionRow,
        )

        session = MagicMock()
        session.flush = AsyncMock()
        repo = AgentPipelineOutputRepository(session)

        lesson_id = uuid4()
        items = [
            QuizQuestion(
                lesson_id=lesson_id,
                question="Q?",
                choices=["A", "B", "C", "D"],
                correct_index=0,
            )
        ]
        await repo.save_quiz_questions("doc-1", items)

        rows = session.add_all.call_args[0][0]
        assert len(rows) == 1
        row = rows[0]
        assert isinstance(row, QuizQuestionRow)
        assert json.loads(row.choices) == ["A", "B", "C", "D"]
