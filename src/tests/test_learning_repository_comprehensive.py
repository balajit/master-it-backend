"""Comprehensive tests for the Learning Repository layer.

Covers: CRUD operations for all entities, batch queries, user progress
upserts, aggregate progress, update operations, edge cases (missing parents,
empty inputs), and the _to_dict helper functions.
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


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mock_session() -> AsyncMock:
    """Build a mock AsyncSession that works as an async context manager."""
    session = AsyncMock()
    session.__aenter__ = AsyncMock(return_value=session)
    session.__aexit__ = AsyncMock(return_value=False)
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    session.refresh = AsyncMock()
    return session


def _patch_session_execute(
    session: AsyncMock, rows: Any = None, rowcount: int = 1
) -> None:
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


# ═══════════════════════════════════════════════════════════════════════════
# 1. Units CRUD
# ═══════════════════════════════════════════════════════════════════════════


class TestCreateUnit:
    def test_success(self) -> None:
        from database.repositories.learning import create_unit

        course = _mock_model(id=1)
        unit = _mock_model(id=42)

        session = _make_mock_session()
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

    def test_create_with_description_and_order(self) -> None:
        from database.repositories.learning import create_unit

        course = _mock_model(id=1)
        unit = _mock_model(id=50)

        session = _make_mock_session()
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
            obj.id = 50

        session.refresh = AsyncMock(side_effect=_fake_refresh)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(
                create_unit(
                    course_id=1, title="Unit B", description="Desc", display_order=2
                )
            )

        assert result == 50
        session.add.assert_called_once()


class TestGetUnit:
    def test_found(self) -> None:
        from database.repositories.learning import get_unit

        unit = _mock_model(
            id=1,
            course_id=1,
            title="U",
            description="D",
            display_order=0,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[unit])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_unit(1))

        assert result is not None
        assert result["id"] == 1
        assert result["title"] == "U"
        assert result["course_id"] == 1
        assert result["description"] == "D"

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
            id=1,
            course_id=1,
            title="A",
            description="",
            display_order=0,
            created_at="",
            updated_at="",
        )
        u2 = _mock_model(
            id=2,
            course_id=1,
            title="B",
            description="",
            display_order=1,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[u1, u2])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_units(course_id=1))

        assert len(result) == 2
        assert result[0]["title"] == "A"
        assert result[1]["title"] == "B"

    def test_empty_list(self) -> None:
        from database.repositories.learning import list_units

        session = _make_mock_session()
        _patch_session_execute(session, rows=[])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_units(course_id=999))

        assert result == []


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

    def test_update_multiple_fields(self) -> None:
        from database.repositories.learning import update_unit

        unit = _mock_model(id=1, title="Old", description="Old D", display_order=0)
        session = _make_mock_session()
        _patch_session_execute(session, rows=[unit])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(
                update_unit(1, title="New", description="New D", display_order=5)
            )

        assert result is True
        assert unit.title == "New"
        assert unit.description == "New D"
        assert unit.display_order == 5


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


# ═══════════════════════════════════════════════════════════════════════════
# 2. Sections CRUD
# ═══════════════════════════════════════════════════════════════════════════


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
            id=1,
            unit_id=1,
            title="S",
            estimated_minutes=30,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[sec])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_section(1))

        assert result is not None
        assert result["title"] == "S"
        assert result["unit_id"] == 1
        assert result["estimated_minutes"] == 30

    def test_not_found(self) -> None:
        from database.repositories.learning import get_section

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_section(999))

        assert result is None


class TestListSections:
    def test_returns_list(self) -> None:
        from database.repositories.learning import list_sections

        s1 = _mock_model(
            id=1,
            unit_id=1,
            title="A",
            estimated_minutes=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[s1])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_sections(unit_id=1))

        assert len(result) == 1
        assert result[0]["title"] == "A"

    def test_empty_list(self) -> None:
        from database.repositories.learning import list_sections

        session = _make_mock_session()
        _patch_session_execute(session, rows=[])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_sections(unit_id=999))

        assert result == []


class TestUpdateSection:
    def test_found(self) -> None:
        from database.repositories.learning import update_section

        sec = _mock_model(id=1, title="Old", estimated_minutes=10, display_order=0)
        session = _make_mock_session()
        _patch_session_execute(session, rows=[sec])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_section(1, title="New", estimated_minutes=20))

        assert result is True
        assert sec.title == "New"
        assert sec.estimated_minutes == 20

    def test_not_found(self) -> None:
        from database.repositories.learning import update_section

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_section(999, title="X"))

        assert result is False


class TestDeleteSection:
    def test_found(self) -> None:
        from database.repositories.learning import delete_section

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_section(1))

        assert result is True
        session.commit.assert_called_once()

    def test_not_found(self) -> None:
        from database.repositories.learning import delete_section

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=0)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_section(999))

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 3. Lessons CRUD
# ═══════════════════════════════════════════════════════════════════════════


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
            id=1,
            section_id=1,
            title="L",
            description="D",
            duration_minutes=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[lesson])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson(1))

        assert result is not None
        assert result["title"] == "L"
        assert result["duration_minutes"] == 10

    def test_not_found(self) -> None:
        from database.repositories.learning import get_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson(999))

        assert result is None


class TestListLessons:
    def test_returns_list(self) -> None:
        from database.repositories.learning import list_lessons

        l1 = _mock_model(
            id=1,
            section_id=1,
            title="L",
            description="",
            duration_minutes=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[l1])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_lessons(section_id=1))

        assert len(result) == 1

    def test_empty_list(self) -> None:
        from database.repositories.learning import list_lessons

        session = _make_mock_session()
        _patch_session_execute(session, rows=[])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_lessons(section_id=999))

        assert result == []


class TestUpdateLesson:
    def test_found(self) -> None:
        from database.repositories.learning import update_lesson

        lesson = _mock_model(
            id=1,
            title="Old",
            description="D",
            duration_minutes=10,
            display_order=0,
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[lesson])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_lesson(1, title="New", duration_minutes=20))

        assert result is True
        assert lesson.title == "New"
        assert lesson.duration_minutes == 20

    def test_not_found(self) -> None:
        from database.repositories.learning import update_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_lesson(999, title="X"))

        assert result is False


class TestDeleteLesson:
    def test_found(self) -> None:
        from database.repositories.learning import delete_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_lesson(1))

        assert result is True

    def test_not_found(self) -> None:
        from database.repositories.learning import delete_lesson

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=0)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_lesson(999))

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 4. Practices CRUD
# ═══════════════════════════════════════════════════════════════════════════


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
            id=1,
            section_id=1,
            title="P",
            required_correct=8,
            total_questions=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[p])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_practice(1))

        assert result is not None
        assert result["required_correct"] == 8
        assert result["total_questions"] == 10

    def test_not_found(self) -> None:
        from database.repositories.learning import get_practice

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_practice(999))

        assert result is None


class TestListPractices:
    def test_returns_list(self) -> None:
        from database.repositories.learning import list_practices

        p = _mock_model(
            id=1,
            section_id=1,
            title="P",
            required_correct=8,
            total_questions=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[p])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_practices(section_id=1))

        assert len(result) == 1

    def test_empty_list(self) -> None:
        from database.repositories.learning import list_practices

        session = _make_mock_session()
        _patch_session_execute(session, rows=[])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_practices(section_id=999))

        assert result == []


class TestUpdatePractice:
    def test_found(self) -> None:
        from database.repositories.learning import update_practice

        p = _mock_model(
            id=1,
            title="Old",
            required_correct=5,
            total_questions=10,
            display_order=0,
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[p])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(
                update_practice(1, title="New", required_correct=8, total_questions=15)
            )

        assert result is True
        assert p.title == "New"
        assert p.required_correct == 8
        assert p.total_questions == 15

    def test_not_found(self) -> None:
        from database.repositories.learning import update_practice

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_practice(999, title="X"))

        assert result is False


class TestDeletePractice:
    def test_found(self) -> None:
        from database.repositories.learning import delete_practice

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_practice(1))

        assert result is True

    def test_not_found(self) -> None:
        from database.repositories.learning import delete_practice

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=0)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_practice(999))

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 5. Quizzes CRUD
# ═══════════════════════════════════════════════════════════════════════════


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
            id=1,
            section_id=1,
            title="Q",
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[q])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_quiz(1))

        assert result is not None
        assert result["title"] == "Q"
        assert result["section_id"] == 1

    def test_not_found(self) -> None:
        from database.repositories.learning import get_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_quiz(999))

        assert result is None


class TestListQuizzes:
    def test_returns_list(self) -> None:
        from database.repositories.learning import list_quizzes

        q = _mock_model(
            id=1,
            section_id=1,
            title="Q",
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[q])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_quizzes(section_id=1))

        assert len(result) == 1

    def test_empty_list(self) -> None:
        from database.repositories.learning import list_quizzes

        session = _make_mock_session()
        _patch_session_execute(session, rows=[])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_quizzes(section_id=999))

        assert result == []


class TestUpdateQuiz:
    def test_found(self) -> None:
        from database.repositories.learning import update_quiz

        q = _mock_model(id=1, title="Old")
        session = _make_mock_session()
        _patch_session_execute(session, rows=[q])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_quiz(1, title="New"))

        assert result is True
        assert q.title == "New"

    def test_not_found(self) -> None:
        from database.repositories.learning import update_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rows=None)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(update_quiz(999, title="X"))

        assert result is False


class TestDeleteQuiz:
    def test_found(self) -> None:
        from database.repositories.learning import delete_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=1)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_quiz(1))

        assert result is True

    def test_not_found(self) -> None:
        from database.repositories.learning import delete_quiz

        session = _make_mock_session()
        _patch_session_execute(session, rowcount=0)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(delete_quiz(999))

        assert result is False


# ═══════════════════════════════════════════════════════════════════════════
# 6. Batch Queries
# ═══════════════════════════════════════════════════════════════════════════


class TestBatchQueriesEmpty:
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
        assert result[10]["user_id"] == 1

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
        assert result[20]["best_score"] == 9.0

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

    def test_multiple_lessons_multiple_sections(self) -> None:
        from database.repositories.learning import list_lessons_for_sections

        l1 = _mock_model(
            id=1,
            section_id=10,
            title="L1",
            description="",
            duration_minutes=10,
            display_order=0,
            created_at="",
            updated_at="",
        )
        l2 = _mock_model(
            id=2,
            section_id=20,
            title="L2",
            description="",
            duration_minutes=15,
            display_order=0,
            created_at="",
            updated_at="",
        )
        session = _make_mock_session()
        _patch_session_execute(session, rows=[l1, l2])

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(list_lessons_for_sections([10, 20]))

        assert len(result) == 2

    def test_batch_progress_empty_result(self) -> None:
        from database.repositories.learning import get_lesson_progress_for_user

        session = _make_mock_session()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        execute_result = MagicMock()
        execute_result.scalars.return_value = scalars_mock
        session.execute = AsyncMock(return_value=execute_result)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_lesson_progress_for_user(1, [10, 20]))

        assert result == {}


# ═══════════════════════════════════════════════════════════════════════════
# 7. User Progress CRUD
# ═══════════════════════════════════════════════════════════════════════════


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
        assert result["completed_at"] == "2026-01-15"

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

    def test_upsert_with_completed_at(self) -> None:
        from database.repositories.learning import upsert_user_lesson_progress

        session = _make_mock_session()
        with patch("database.repositories.learning.AsyncSession", return_value=session):
            asyncio.run(
                upsert_user_lesson_progress(
                    1, 10, status="COMPLETED", completed_at="2026-01-15T10:00:00"
                )
            )

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
        assert result["status"] == "MASTERED"

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
            asyncio.run(
                upsert_user_practice_progress(
                    1, 20, attempts=3, best_score=8.5, status="MASTERED"
                )
            )

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
        assert result["completed_at"] == "2026-01-20"

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

    def test_upsert_with_completed_at(self) -> None:
        from database.repositories.learning import upsert_user_quiz_progress

        session = _make_mock_session()
        with patch("database.repositories.learning.AsyncSession", return_value=session):
            asyncio.run(
                upsert_user_quiz_progress(
                    1, 30, score=90.0, completed_at="2026-01-20T12:00:00"
                )
            )

        session.execute.assert_called_once()
        session.commit.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# 8. Aggregate Progress
# ═══════════════════════════════════════════════════════════════════════════


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

    def test_with_data(self) -> None:
        from database.repositories.learning import get_all_user_progress

        lesson_row = MagicMock()
        lesson_row.user_id = 1
        lesson_row.lesson_id = 10
        lesson_row.status = "COMPLETED"
        lesson_row.completed_at = "2026-01-15"

        practice_row = MagicMock()
        practice_row.user_id = 1
        practice_row.practice_id = 20
        practice_row.attempts = 3
        practice_row.best_score = 9.0
        practice_row.status = "MASTERED"

        quiz_row = MagicMock()
        quiz_row.user_id = 1
        quiz_row.quiz_id = 30
        quiz_row.score = 85.0
        quiz_row.completed_at = "2026-01-20"

        call_count = 0

        async def _fake_execute(stmt: Any) -> MagicMock:
            nonlocal call_count
            call_count += 1
            scalars_mock = MagicMock()
            if call_count == 1:
                scalars_mock.all.return_value = [lesson_row]
            elif call_count == 2:
                scalars_mock.all.return_value = [practice_row]
            else:
                scalars_mock.all.return_value = [quiz_row]
            execute_result = MagicMock()
            execute_result.scalars.return_value = scalars_mock
            return execute_result

        session = _make_mock_session()
        session.execute = AsyncMock(side_effect=_fake_execute)

        with patch("database.repositories.learning.AsyncSession", return_value=session):
            result = asyncio.run(get_all_user_progress(1))

        assert len(result["lessons"]) == 1
        assert result["lessons"][0]["lesson_id"] == 10
        assert len(result["practices"]) == 1
        assert result["practices"][0]["practice_id"] == 20
        assert len(result["quizzes"]) == 1
        assert result["quizzes"][0]["quiz_id"] == 30


# ═══════════════════════════════════════════════════════════════════════════
# 9. to_dict helper coverage
# ═══════════════════════════════════════════════════════════════════════════


class TestToDictHelpers:
    """Verify _to_dict helpers return correct dict shapes."""

    def test_unit_to_dict(self) -> None:
        from database.repositories.learning import _unit_to_dict

        unit = _mock_model(
            id=1,
            course_id=1,
            title="U",
            description="D",
            display_order=0,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        result = _unit_to_dict(unit)
        assert result["id"] == 1
        assert result["course_id"] == 1
        assert result["title"] == "U"
        assert result["description"] == "D"
        assert result["display_order"] == 0

    def test_section_to_dict(self) -> None:
        from database.repositories.learning import _section_to_dict

        sec = _mock_model(
            id=1,
            unit_id=1,
            title="S",
            estimated_minutes=30,
            display_order=0,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        result = _section_to_dict(sec)
        assert result["id"] == 1
        assert result["unit_id"] == 1
        assert result["title"] == "S"
        assert result["estimated_minutes"] == 30

    def test_lesson_to_dict(self) -> None:
        from database.repositories.learning import _lesson_to_dict

        lesson = _mock_model(
            id=1,
            section_id=1,
            title="L",
            description="D",
            duration_minutes=10,
            display_order=0,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        result = _lesson_to_dict(lesson)
        assert result["id"] == 1
        assert result["section_id"] == 1
        assert result["title"] == "L"
        assert result["duration_minutes"] == 10

    def test_practice_to_dict(self) -> None:
        from database.repositories.learning import _practice_to_dict

        p = _mock_model(
            id=1,
            section_id=1,
            title="P",
            required_correct=8,
            total_questions=10,
            display_order=0,
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        result = _practice_to_dict(p)
        assert result["id"] == 1
        assert result["required_correct"] == 8
        assert result["total_questions"] == 10

    def test_quiz_to_dict(self) -> None:
        from database.repositories.learning import _quiz_to_dict

        q = _mock_model(
            id=1,
            section_id=1,
            title="Q",
            created_at="2026-01-01",
            updated_at="2026-01-01",
        )
        result = _quiz_to_dict(q)
        assert result["id"] == 1
        assert result["title"] == "Q"
        assert result["section_id"] == 1
