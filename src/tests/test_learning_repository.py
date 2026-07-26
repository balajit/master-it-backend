"""Tests for the Learning repository layer.

Covers CRUD operations, batch queries, and progress functions by mocking AsyncSession.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_src_dir: str = str(Path(__file__).resolve().parent.parent)
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)


def _make_mock_session() -> AsyncMock:
    """Build a mock AsyncSession that works as an async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _patch_session_execute(session: AsyncMock, rows: Any = None, rowcount: int = 1) -> None:
    """Configure session.execute to return mock results."""
    scalars_mock = MagicMock()
    if rows is None:
        scalars_mock.first.return_value = None
        scalars_mock.all.return_value = []
    elif isinstance(rows, list):
        scalars_mock.first.return_value = rows[0] if rows else None
        scalars_mock.all.return_value = rows
    else:
        scalars_mock.first.return_value = rows
        scalars_mock.all.return_value = []

    execute_result = MagicMock()
    execute_result.scalars.return_value = scalars_mock
    execute_result.rowcount = rowcount
    session.execute = AsyncMock(return_value=execute_result)


def _mock_model(**attrs: Any) -> MagicMock:
    """Build a MagicMock that behaves like an ORM model instance."""
    m = MagicMock()
    for k, v in attrs.items():
        setattr(m, k, v)
    return m


# ── Units ───────────────────────────────────────────────────────────────────


class TestCreateUnit:
    def test_success(self) -> None:
        from database.repositories.learning import create_unit

        course = _mock_model(id=1)
        unit = _mock_model(id=42)

        session = _make_mock_session()

        # First call: course lookup returns course
        # Second call (after add): nothing (but we don't care)
        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count == 1:
                scalars.first.return_value = course
            else:
                scalars.first.return_value = unit
            result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=_fake_execute)

        async def _fake_refresh(obj: Any) -> None:
            obj.id = 42

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(create_unit(course_id=1, title="Unit A"))

        assert result == 42
        session.add.assert_called_once()
        session.commit.assert_called_once()

    def test_raises_when_course_not_found(self) -> None:
        from database.repositories.learning import create_unit

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            with pytest.raises(ValueError, match="Course 999 not found"):
                asyncio.run(create_unit(course_id=999, title="X"))


class TestGetUnit:
    def test_found(self) -> None:
        from database.repositories.learning import get_unit

        unit = _mock_model(
            id=1, course_id=1, title="U", description="D",
            display_order=0, created_at="2026-01-01", updated_at="2026-01-01",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[unit])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_unit(1))

        assert result is not None
        assert result["id"] == 1
        assert result["title"] == "U"

    def test_not_found(self) -> None:
        from database.repositories.learning import get_unit

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_unit(999))

        assert result is None


class TestListUnits:
    def test_returns_ordered_list(self) -> None:
        from database.repositories.learning import list_units

        u1 = _mock_model(
            id=1, course_id=1, title="A", description="",
            display_order=0, created_at="", updated_at="",
        )
        u2 = _mock_model(
            id=2, course_id=1, title="B", description="",
            display_order=1, created_at="", updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[u1, u2])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_units(course_id=1))

        assert len(result) == 2
        assert result[0]["title"] == "A"
        assert result[1]["title"] == "B"


class TestUpdateUnit:
    def test_found(self) -> None:
        from database.repositories.learning import update_unit

        unit = _mock_model(id=1, title="Old", description="D", display_order=0)
        session = _make_mock_session()
        _patch_session_execute(session, rows=[unit])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_unit(1, title="New"))

        assert result is True
        session.commit.assert_called_once()

    def test_not_found(self) -> None:
        from database.repositories.learning import update_unit

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_unit(999, title="X"))

        assert result is False


class TestDeleteUnit:
    def test_found(self) -> None:
        from database.repositories.learning import delete_unit

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_unit(1))

        assert result is True

    def test_not_found(self) -> None:
        from database.repositories.learning import delete_unit

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=0)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_unit(999))

        assert result is False


# ── Sections ────────────────────────────────────────────────────────────────


class TestCreateSection:
    def test_success(self) -> None:
        from database.repositories.learning import create_section

        unit = _mock_model(id=1)
        section = _mock_model(id=10)

        session = _make_mock_session()
        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count == 1:
                scalars.first.return_value = unit
            else:
                scalars.first.return_value = section
            result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=_fake_execute)

        async def _fake_refresh(obj: Any) -> None:
            obj.id = 10

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(create_section(unit_id=1, title="S1"))

        assert result == 10

    def test_raises_when_unit_not_found(self) -> None:
        from database.repositories.learning import create_section

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            with pytest.raises(ValueError, match="Unit 999 not found"):
                asyncio.run(create_section(unit_id=999, title="X"))


class TestGetSection:
    def test_found(self) -> None:
        from database.repositories.learning import get_section

        sec = _mock_model(
            id=1, unit_id=1, title="S", estimated_minutes=30,
            display_order=0, created_at="", updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[sec])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_section(1))

        assert result is not None
        assert result["title"] == "S"

    def test_not_found(self) -> None:
        from database.repositories.learning import get_section

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_section(999))

        assert result is None


class TestDeleteSection:
    def test_found(self) -> None:
        from database.repositories.learning import delete_section

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_section(1))

        assert result is True
        session.commit.assert_called_once()


# ── Lessons ─────────────────────────────────────────────────────────────────


class TestCreateLesson:
    def test_success(self) -> None:
        from database.repositories.learning import create_lesson

        section = _mock_model(id=1)
        lesson = _mock_model(id=10)

        session = _make_mock_session()
        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count == 1:
                scalars.first.return_value = section
            else:
                scalars.first.return_value = lesson
            result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=_fake_execute)

        async def _fake_refresh(obj: Any) -> None:
            obj.id = 10

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(create_lesson(section_id=1, title="L1"))

        assert result == 10

    def test_raises_when_section_not_found(self) -> None:
        from database.repositories.learning import create_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            with pytest.raises(ValueError, match="Section 999 not found"):
                asyncio.run(create_lesson(section_id=999, title="X"))


class TestGetLesson:
    def test_found(self) -> None:
        from database.repositories.learning import get_lesson

        lesson = _mock_model(
            id=1, section_id=1, title="L", description="D",
            duration_minutes=10, display_order=0, created_at="", updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[lesson])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson(1))

        assert result is not None
        assert result["title"] == "L"

    def test_not_found(self) -> None:
        from database.repositories.learning import get_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson(999))

        assert result is None


# ── Practices ───────────────────────────────────────────────────────────────


class TestCreatePractice:
    def test_success(self) -> None:
        from database.repositories.learning import create_practice

        section = _mock_model(id=1)
        practice = _mock_model(id=10)

        session = _make_mock_session()
        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count == 1:
                scalars.first.return_value = section
            else:
                scalars.first.return_value = practice
            result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=_fake_execute)

        async def _fake_refresh(obj: Any) -> None:
            obj.id = 10

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(create_practice(section_id=1, title="P1"))

        assert result == 10

    def test_raises_when_section_not_found(self) -> None:
        from database.repositories.learning import create_practice

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            with pytest.raises(ValueError, match="Section 999 not found"):
                asyncio.run(create_practice(section_id=999, title="X"))


class TestGetPractice:
    def test_found(self) -> None:
        from database.repositories.learning import get_practice

        p = _mock_model(
            id=1, section_id=1, title="P", required_correct=8,
            total_questions=10, display_order=0, created_at="", updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[p])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_practice(1))

        assert result is not None
        assert result["required_correct"] == 8

    def test_not_found(self) -> None:
        from database.repositories.learning import get_practice

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_practice(999))

        assert result is None


# ── Quizzes ─────────────────────────────────────────────────────────────────


class TestCreateQuiz:
    def test_success(self) -> None:
        from database.repositories.learning import create_quiz

        section = _mock_model(id=1)
        quiz = _mock_model(id=10)

        session = _make_mock_session()
        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            scalars = MagicMock()
            if call_count == 1:
                scalars.first.return_value = section
            else:
                scalars.first.return_value = quiz
            result.scalars.return_value = scalars
            return result

        session.execute = AsyncMock(side_effect=_fake_execute)

        async def _fake_refresh(obj: Any) -> None:
            obj.id = 10

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(create_quiz(section_id=1, title="Q1"))

        assert result == 10

    def test_raises_when_section_not_found(self) -> None:
        from database.repositories.learning import create_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            with pytest.raises(ValueError, match="Section 999 not found"):
                asyncio.run(create_quiz(section_id=999, title="X"))


class TestGetQuiz:
    def test_found(self) -> None:
        from database.repositories.learning import get_quiz

        q = _mock_model(
            id=1, section_id=1, title="Q", created_at="", updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[q])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_quiz(1))

        assert result is not None
        assert result["title"] == "Q"

    def test_not_found(self) -> None:
        from database.repositories.learning import get_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_quiz(999))

        assert result is None


# ── Batch Queries ───────────────────────────────────────────────────────────


class TestBatchQueries:
    def test_list_lessons_empty_input(self) -> None:
        from database.repositories.learning import list_lessons_for_sections
        result = asyncio.run(list_lessons_for_sections([]))
        assert result == []

    def test_list_practices_empty_input(self) -> None:
        from database.repositories.learning import list_practices_for_sections
        result = asyncio.run(list_practices_for_sections([]))
        assert result == []

    def test_list_quizzes_empty_input(self) -> None:
        from database.repositories.learning import list_quizzes_for_sections
        result = asyncio.run(list_quizzes_for_sections([]))
        assert result == []

    def test_get_lesson_progress_empty_input(self) -> None:
        from database.repositories.learning import get_lesson_progress_for_user
        result = asyncio.run(get_lesson_progress_for_user(1, []))
        assert result == {}

    def test_get_practice_progress_empty_input(self) -> None:
        from database.repositories.learning import get_practice_progress_for_user
        result = asyncio.run(get_practice_progress_for_user(1, []))
        assert result == {}

    def test_get_quiz_progress_empty_input(self) -> None:
        from database.repositories.learning import get_quiz_progress_for_user
        result = asyncio.run(get_quiz_progress_for_user(1, []))
        assert result == {}


class TestBatchQueriesWithData:
    def test_lessons_grouped_by_key(self) -> None:
        from database.repositories.learning import get_lesson_progress_for_user

        row = MagicMock()
        row.user_id = 1
        row.lesson_id = 10
        row.status = "COMPLETED"
        row.completed_at = "2026-01-15"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [row]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson_progress_for_user(1, [10]))

        assert 10 in result
        assert result[10]["status"] == "COMPLETED"

    def test_practices_grouped_by_key(self) -> None:
        from database.repositories.learning import get_practice_progress_for_user

        row = MagicMock()
        row.user_id = 1
        row.practice_id = 20
        row.attempts = 3
        row.best_score = 9.0
        row.status = "MASTERED"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [row]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_practice_progress_for_user(1, [20]))

        assert 20 in result
        assert result[20]["attempts"] == 3

    def test_quizzes_grouped_by_key(self) -> None:
        from database.repositories.learning import get_quiz_progress_for_user

        row = MagicMock()
        row.user_id = 1
        row.quiz_id = 30
        row.score = 85.0
        row.completed_at = "2026-01-20"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [row]
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_quiz_progress_for_user(1, [30]))

        assert 30 in result
        assert result[30]["score"] == 85.0


# ── User Progress CRUD ──────────────────────────────────────────────────────


class TestUserLessonProgress:
    def test_get_found(self) -> None:
        from database.repositories.learning import get_user_lesson_progress

        row = MagicMock()
        row.user_id = 1
        row.lesson_id = 10
        row.status = "COMPLETED"
        row.completed_at = "2026-01-15"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = row
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_lesson_progress(1, 10))

        assert result is not None
        assert result["status"] == "COMPLETED"

    def test_get_not_found(self) -> None:
        from database.repositories.learning import get_user_lesson_progress

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = None
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_lesson_progress(1, 999))

        assert result is None

    def test_upsert(self) -> None:
        from database.repositories.learning import upsert_user_lesson_progress

        session = _make_mock_session()
        with patch("database.repositories.learning.AsyncSession", return_value=session):
            asyncio.run(upsert_user_lesson_progress(1, 10, status="COMPLETED"))

        session.execute.assert_called_once()
        session.commit.assert_called_once()


class TestUserPracticeProgress:
    def test_get_found(self) -> None:
        from database.repositories.learning import get_user_practice_progress

        row = MagicMock()
        row.user_id = 1
        row.practice_id = 20
        row.attempts = 5
        row.best_score = 9.0
        row.status = "MASTERED"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = row
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_practice_progress(1, 20))

        assert result is not None
        assert result["attempts"] == 5
        assert result["best_score"] == 9.0

    def test_get_not_found(self) -> None:
        from database.repositories.learning import get_user_practice_progress

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = None
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_practice_progress(1, 999))

        assert result is None

    def test_upsert(self) -> None:
        from database.repositories.learning import upsert_user_practice_progress

        session = _make_mock_session()
        with patch("database.repositories.learning.AsyncSession", return_value=session):
            asyncio.run(upsert_user_practice_progress(
                1, 20, attempts=3, best_score=8.5, status="MASTERED",
            ))

        session.execute.assert_called_once()
        session.commit.assert_called_once()


class TestUserQuizProgress:
    def test_get_found(self) -> None:
        from database.repositories.learning import get_user_quiz_progress

        row = MagicMock()
        row.user_id = 1
        row.quiz_id = 30
        row.score = 85.0
        row.completed_at = "2026-01-20"

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = row
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_quiz_progress(1, 30))

        assert result is not None
        assert result["score"] == 85.0

    def test_get_not_found(self) -> None:
        from database.repositories.learning import get_user_quiz_progress

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.first.return_value = None
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_user_quiz_progress(1, 999))

        assert result is None

    def test_upsert(self) -> None:
        from database.repositories.learning import upsert_user_quiz_progress

        session = _make_mock_session()
        with patch("database.repositories.learning.AsyncSession", return_value=session):
            asyncio.run(upsert_user_quiz_progress(1, 30, score=90.0))

        session.execute.assert_called_once()
        session.commit.assert_called_once()


# ── Aggregate Progress ──────────────────────────────────────────────────────


class TestGetAllUserProgress:
    def test_empty(self) -> None:
        from database.repositories.learning import get_all_user_progress

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_all_user_progress(1))

        assert result["lessons"] == []
        assert result["practices"] == []
        assert result["quizzes"] == []
